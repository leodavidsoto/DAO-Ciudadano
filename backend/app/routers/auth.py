"""
Authentication Router
Handles ClaveÚnica, NFC, and Liveness detection endpoints
"""
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from typing import Optional
import logging
import asyncio
import re
import uuid
import base64
import io
from PIL import Image

from ..models import (
    ClaveUnicaRequest, ClaveUnicaResponse,
    NFCRequest, NFCResponse, LivenessResponse,
    User, UserRegisterRequest, UserLoginRequest, UserResponse,
)
from ..core import readiness
from ..core.config import settings
from ..core.crypto import encrypt, decrypt
from ..core.database import users_collection
from ..core.identity import lookup_key, lookup_key_candidates
from ..core.security import generate_short_hash

logger = logging.getLogger(__name__)

DEMO_ASSURANCE_LEVEL = "DEMO_UNVERIFIED"


def require_non_production_identity_demo() -> None:
    """Fail closed when a simulated identity flow reaches production.

    None of these routes currently authenticates civil identity: ClaveUnica
    and NFC are simulations, a single-image LLM is not a liveness verifier,
    and RUT + email only proves knowledge of submitted data. A router-level
    dependency runs before endpoint logic and before any database mutation.
    """
    if settings.is_production:
        raise HTTPException(
            status_code=503,
            detail=(
                "Los flujos de identidad de este piloto están deshabilitados "
                "en producción hasta integrar un verificador de identidad real."
            ),
        )


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    dependencies=[Depends(require_non_production_identity_demo)],
)


async def mock_delay(seconds: float = 0.1):
    """Simulated processing delay"""
    await asyncio.sleep(seconds)


@router.post("/clave-unica", response_model=ClaveUnicaResponse)
async def authenticate_clave_unica(request: ClaveUnicaRequest):
    """
    Authenticate user with ClaveÚnica (Chilean government SSO)
    
    In production, this would redirect to the official ClaveÚnica portal.
    Currently uses mock authentication for development.
    """
    try:
        await mock_delay(0.12)
        
        if not request.rut or len(request.rut) < 8:
            return ClaveUnicaResponse(ok=False, error="RUT inválido")
        
        # Ephemeral demo identifier: deliberately neither stable nor derived
        # from the RUT, and impossible to mistake for a government identifier.
        subject_id = f"demo:clave-unica:{uuid.uuid4()}"
        
        return ClaveUnicaResponse(
            ok=True,
            subject_id=subject_id,
            assurance_level=DEMO_ASSURANCE_LEVEL,
        )
        
    except Exception as e:
        logger.error(f"Error in ClaveÚnica auth: {e}")
        return ClaveUnicaResponse(ok=False, error="No se pudo completar la autenticación.")


@router.post("/nfc", response_model=NFCResponse)
async def authenticate_nfc(request: Optional[NFCRequest] = None):
    """
    Authenticate using NFC chip in Chilean ID card

    DEMO MODE: no cryptographic verification of the chip happens yet
    (real PACE reading is ROADMAP task 4.2). If the client sends a tag serial,
    the API derives a non-sensitive demo identifier from it; otherwise a random
    demo identifier is generated. Neither result proves the tag is a cédula.
    """
    try:
        await mock_delay(0.16)

        if request and request.chip_serial:
            chip_serial = (
                "DEMO-NFC-CLIENT-"
                + generate_short_hash(request.chip_serial, length=12).upper()
            )
        else:
            chip_serial = f"DEMO-NFC-RANDOM-{uuid.uuid4().hex[:8].upper()}"
        doc_hash = f"0x{generate_short_hash('nfc_doc_' + chip_serial)}"
        
        return NFCResponse(
            ok=True,
            chip_serial=chip_serial,
            doc_hash=doc_hash
        )
        
    except Exception as e:
        logger.error(f"Error in NFC auth: {e}")
        return NFCResponse(ok=False, error="No se pudo completar la lectura NFC.")


@router.post("/liveness", response_model=LivenessResponse)
async def analyze_liveness(file: UploadFile = File(...)):
    """
    Run a demo-only visual heuristic over an uploaded image.

    A single still image cannot prove liveness. This route stays useful for
    interface testing outside production, but its result is not identity
    evidence and is never persisted as one.
    """
    try:
        if not file.content_type or not file.content_type.startswith('image/'):
            return LivenessResponse(ok=False, error="El archivo debe ser una imagen")
        
        # Read and validate image
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:  # 10MB limit
            return LivenessResponse(ok=False, error="Imagen muy grande (máximo 10MB)")
        
        try:
            image = Image.open(io.BytesIO(contents))
            image.verify()
        except Exception:
            return LivenessResponse(ok=False, error="Imagen inválida")
        
        # Convert to base64 for LLM
        base64_image = base64.b64encode(contents).decode('utf-8')
        
        # Check for API key
        api_key = settings.EMERGENT_LLM_KEY
        if not api_key:
            # No provider, no score. Returning a fixed 0.85 here is exactly the
            # fabricated-value pattern AGENTS.md forbids: the client cannot
            # tell it apart from a real measurement, and this project already
            # shipped that number to production once.
            logger.warning("No EMERGENT_LLM_KEY configured; liveness returns no score")
            score = None
            analysis = (
                "DEMO: no hay proveedor de análisis configurado, así que no se "
                "calculó ningún puntaje. Este flujo no verifica presencia en vivo."
            )
        else:
            # Real LLM analysis
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
                
                chat = LlmChat(
                    api_key=api_key,
                    session_id=f"liveness_{uuid.uuid4()}",
                    system_message="""Evalúa solo indicios visuales en esta imagen.
                    Una imagen estática no permite verificar presencia en vivo,
                    así que no afirmes que la identidad o el liveness están
                    verificados. El score representa únicamente qué tan
                    consistente parece la imagen con un selfie normal.

                    Formato: "SCORE: 0.85 | ANÁLISIS: [tu análisis detallado]" """
                ).with_model("openai", "gpt-4o")
                
                image_content = ImageContent(image_base64=base64_image)
                user_message = UserMessage(
                    text=(
                        "Describe indicios visuales de un selfie sin afirmar que "
                        "la presencia en vivo está verificada."
                    ),
                    file_contents=[image_content]
                )
                
                response = await chat.send_message(user_message)
                
                # Parse response
                score = 0.5
                analysis = response
                
                if "SCORE:" in response:
                    try:
                        score_part = response.split("SCORE:")[1].split("|")[0].strip()
                        score = float(score_part)
                        if "|" in response:
                            analysis = response.split("|", 1)[1].replace("ANÁLISIS:", "").strip()
                    except (ValueError, IndexError):
                        pass
                        
            except ImportError:
                logger.warning("emergentintegrations not available; liveness returns no score")
                score = None
                analysis = (
                    "DEMO: la biblioteca de análisis no está disponible, así "
                    "que no se calculó ningún puntaje. Este flujo no verifica "
                    "presencia en vivo."
                )
            except Exception as e:
                # Never surface the provider's error text (it can carry URLs,
                # model ids or key fragments) as if it were an analysis result.
                logger.error(f"LLM error: {e}")
                score = None
                analysis = (
                    "DEMO: el análisis falló; no se calculó ningún puntaje. "
                    "Este flujo no verifica presencia en vivo."
                )

        if not analysis.startswith("DEMO:"):
            analysis = (
                "DEMO: heurística sobre una sola imagen; no constituye una "
                f"verificación de presencia en vivo. {analysis}"
            )
        
        return LivenessResponse(
            ok=True,
            score=score,
            analysis=analysis
        )
        
    except Exception as e:
        logger.error(f"Error in liveness detection: {e}")
        return LivenessResponse(ok=False, error="No se pudo procesar la imagen.")


# === RUT + Email Authentication (Simple registration while awaiting ClaveÚnica sandbox) ===


def validate_rut(rut: str) -> bool:
    """Validate Chilean RUT format and check digit"""
    # Clean RUT
    rut = rut.replace(".", "").replace("-", "").upper()
    
    if len(rut) < 8 or len(rut) > 12:
        return False
    
    # Separate number and check digit
    body = rut[:-1]
    check = rut[-1]
    
    try:
        # Calculate check digit
        sum_val = 0
        multiplier = 2
        for digit in reversed(body):
            sum_val += int(digit) * multiplier
            multiplier = multiplier + 1 if multiplier < 7 else 2
        
        remainder = 11 - (sum_val % 11)
        if remainder == 11:
            expected = "0"
        elif remainder == 10:
            expected = "K"
        else:
            expected = str(remainder)
        
        return check == expected
    except ValueError:
        return False


def format_rut(rut: str) -> str:
    """Format RUT to standard format (12.345.678-9)"""
    rut = rut.replace(".", "").replace("-", "").upper()
    body = rut[:-1]
    check = rut[-1]
    
    # Format with dots
    formatted = ""
    for i, char in enumerate(reversed(body)):
        if i > 0 and i % 3 == 0:
            formatted = "." + formatted
        formatted = char + formatted
    
    return f"{formatted}-{check}"


@router.post("/register", response_model=UserResponse)
async def register_user(request: UserRegisterRequest):
    """
    Register a new user with RUT and email.

    Simple registration while waiting for ClaveÚnica sandbox access.
    Validates RUT format, cifra el RUT/email/nombre antes de guardarlos
    (nunca en texto plano) y busca duplicados por índice ciego, no por
    el valor cifrado (que es distinto cada vez por el IV de Fernet).
    """
    readiness.require("IDENTITY_PEPPER", "registrar ciudadanos")
    readiness.require("PII_ENCRYPTION_KEY", "registrar ciudadanos")

    try:
        await mock_delay(0.1)

        # Validate RUT
        if not validate_rut(request.rut):
            return UserResponse(ok=False, error="RUT inválido. Verifica el formato (ej: 12345678-9)")

        # Format RUT
        formatted_rut = format_rut(request.rut)

        # Validate email
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, request.email):
            return UserResponse(ok=False, error="Email inválido")

        normalized_email = request.email.lower()
        rut_key = lookup_key(formatted_rut, domain="rut")
        email_key = lookup_key(normalized_email, domain="email")

        # Check if RUT already registered (por índice ciego, no por el
        # valor cifrado -- dos cifrados del mismo RUT no son iguales).
        #
        # Se buscan también las claves derivadas del pepper anterior: durante
        # una rotación, mirar solo la vigente daría "no existe" para alguien ya
        # registrado y crearía un duplicado que el índice único rechazaría con
        # un error opaco.
        existing = await users_collection().find_one(
            {"rut_key": {"$in": lookup_key_candidates(formatted_rut, domain="rut")}}
        )
        if existing:
            return UserResponse(ok=False, error="Este RUT ya está registrado")

        existing_email = await users_collection().find_one(
            {"email_key": {"$in": lookup_key_candidates(normalized_email, domain="email")}}
        )
        if existing_email:
            return UserResponse(ok=False, error="Este email ya está registrado")

        # Create user (PII cifrada en reposo)
        user = User(
            rut=encrypt(formatted_rut),
            rut_key=rut_key,
            email=encrypt(normalized_email),
            email_key=email_key,
            nombre=encrypt(request.nombre.strip()),
            apellido=encrypt(request.apellido.strip()),
        )

        await users_collection().insert_one(user.model_dump())

        logger.info(f"New user registered (rut_key={rut_key[:8]}...)")

        return UserResponse(
            ok=True,
            user_id=user.id,
            rut=formatted_rut,
            email=normalized_email,
            nombre=request.nombre,
            subject_id=f"demo:user:{user.id}",
            assurance_level=DEMO_ASSURANCE_LEVEL,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in registration: {e}")
        return UserResponse(ok=False, error="No se pudo completar el registro. Intenta de nuevo.")


@router.post("/login", response_model=UserResponse)
async def login_user(request: UserLoginRequest):
    """
    Login with RUT and email.

    Busca por índice ciego (rut_key/email_key), descifra solo el
    registro encontrado para devolver los datos en la respuesta.
    """
    readiness.require("IDENTITY_PEPPER", "iniciar sesión")
    readiness.require("PII_ENCRYPTION_KEY", "iniciar sesión")

    try:
        await mock_delay(0.1)

        formatted_rut = format_rut(request.rut)
        normalized_email = request.email.lower()

        # `$in` con las claves del pepper vigente y del anterior: durante una
        # rotación, un usuario aún no reindexado tiene que poder entrar. Fuera
        # de una rotación la lista tiene un solo elemento y la consulta es la
        # misma de siempre.
        user_doc = await users_collection().find_one({
            "rut_key": {"$in": lookup_key_candidates(formatted_rut, domain="rut")},
            "email_key": {"$in": lookup_key_candidates(normalized_email, domain="email")},
        })

        if not user_doc:
            return UserResponse(ok=False, error="RUT o email incorrectos")

        if user_doc.get("status") != "active":
            return UserResponse(ok=False, error="Cuenta desactivada")

        # Se registra la clave REAL del documento, no la recalculada: durante
        # una rotación pueden diferir, y la útil para rastrear es la guardada.
        logger.info(f"User logged in (rut_key={str(user_doc.get('rut_key'))[:8]}...)")

        try:
            nombre = decrypt(user_doc.get("nombre"))
        except ValueError:
            nombre = None

        return UserResponse(
            ok=True,
            user_id=user_doc.get("id"),
            rut=formatted_rut,
            email=normalized_email,
            nombre=nombre,
            subject_id=f"demo:user:{user_doc.get('id')}",
            assurance_level=DEMO_ASSURANCE_LEVEL,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in login: {e}")
        return UserResponse(ok=False, error="No se pudo iniciar sesión. Intenta de nuevo.")
