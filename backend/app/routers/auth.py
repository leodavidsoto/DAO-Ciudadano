"""
Authentication Router
Handles ClaveÚnica, NFC, and Liveness detection endpoints
"""
from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import Optional
import logging
import asyncio
import uuid
import base64
import io
from PIL import Image

from ..models import (
    ClaveUnicaRequest, ClaveUnicaResponse,
    NFCRequest, NFCResponse, LivenessResponse, IdentityEvent
)
from ..core.security import generate_short_hash
from ..core.database import identity_events_collection
from ..core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
        
        # Mock successful authentication
        subject_id = f"claveunica:{request.rut}"
        
        # Store identity event
        event = IdentityEvent(
            user_id=request.rut,
            event_type="clave_unica",
            hash_value=generate_short_hash(request.rut),
            verifier="claveunica_gov"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        return ClaveUnicaResponse(
            ok=True,
            subject_id=subject_id,
            assurance_level="AL2"
        )
        
    except Exception as e:
        logger.error(f"Error in ClaveÚnica auth: {e}")
        return ClaveUnicaResponse(ok=False, error=str(e))


@router.post("/nfc", response_model=NFCResponse)
async def authenticate_nfc(request: Optional[NFCRequest] = None):
    """
    Authenticate using NFC chip in Chilean ID card

    DEMO MODE: no cryptographic verification of the chip happens yet
    (real PACE reading is ROADMAP task 4.2). If the client sends the chip
    serial it captured, it is used as-is; otherwise a demo serial is generated.
    """
    try:
        await mock_delay(0.16)

        if request and request.chip_serial:
            chip_serial = request.chip_serial
        else:
            chip_serial = f"NFC-CL-CH-{uuid.uuid4().hex[:8].upper()}"
        doc_hash = f"0x{generate_short_hash('nfc_doc_' + chip_serial)}"
        
        # Store identity event
        event = IdentityEvent(
            user_id=chip_serial,
            event_type="nfc",
            hash_value=doc_hash,
            verifier="chile_gov_nfc"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        return NFCResponse(
            ok=True,
            chip_serial=chip_serial,
            doc_hash=doc_hash
        )
        
    except Exception as e:
        logger.error(f"Error in NFC auth: {e}")
        return NFCResponse(ok=False, error=str(e))


@router.post("/liveness", response_model=LivenessResponse)
async def analyze_liveness(file: UploadFile = File(...)):
    """
    Analyze uploaded image for liveness detection
    
    Uses AI vision to determine if the image shows a real person
    taking a live selfie vs a photo, video, or deepfake.
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
            # Return mock response if no API key
            logger.warning("No EMERGENT_LLM_KEY configured, using mock liveness")
            score = 0.85
            analysis = "Mock liveness detection: imagen parece ser genuina (API key no configurada)"
        else:
            # Real LLM analysis
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
                
                chat = LlmChat(
                    api_key=api_key,
                    session_id=f"liveness_{uuid.uuid4()}",
                    system_message="""Eres un experto en detección de vida (liveness detection). 
                    Analiza esta imagen y determina si muestra una persona real en vivo o si es una foto/video/deepfake.
                    
                    Evalúa:
                    1. Naturalidad de la pose y expresión
                    2. Calidad de la imagen (¿parece tomada en vivo?)
                    3. Signos de vida como micro-movimientos o inconsistencias de deepfake
                    4. Contexto y fondo
                    
                    Responde con un score de 0.0 a 1.0 donde:
                    - 0.0-0.3: Definitivamente no es una persona real
                    - 0.4-0.6: Dudoso, posible foto o video
                    - 0.7-0.9: Probablemente una persona real
                    - 0.9-1.0: Definitivamente una persona real en vivo
                    
                    Formato: "SCORE: 0.85 | ANÁLISIS: [tu análisis detallado]" """
                ).with_model("openai", "gpt-4o")
                
                image_content = ImageContent(image_base64=base64_image)
                user_message = UserMessage(
                    text="Analiza esta imagen para detección de vida (liveness detection). ¿Es una persona real tomándose un selfie ahora mismo?",
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
                    except:
                        pass
                        
            except ImportError:
                logger.warning("emergentintegrations not available, using mock")
                score = 0.85
                analysis = "Mock liveness: biblioteca no disponible"
            except Exception as e:
                logger.error(f"LLM error: {e}")
                score = 0.5
                analysis = f"Error en análisis: {str(e)}"
        
        # Store identity event
        event = IdentityEvent(
            user_id=generate_short_hash(base64_image[:100]),
            event_type="liveness",
            hash_value=generate_short_hash(f"liveness_{score}"),
            verifier="llm_vision_ai"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        return LivenessResponse(
            ok=True,
            score=score,
            analysis=analysis
        )
        
    except Exception as e:
        logger.error(f"Error in liveness detection: {e}")
        return LivenessResponse(ok=False, error=f"Error en análisis: {str(e)}")


# === RUT + Email Authentication (Simple registration while awaiting ClaveÚnica sandbox) ===

from ..models import User, UserRegisterRequest, UserLoginRequest, UserResponse
from ..core.database import users_collection
from ..core import readiness
from ..core.crypto import encrypt, decrypt
from ..core.identity import lookup_key
import re


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
        # valor cifrado -- dos cifrados del mismo RUT no son iguales)
        existing = await users_collection().find_one({"rut_key": rut_key})
        if existing:
            return UserResponse(ok=False, error="Este RUT ya está registrado")

        existing_email = await users_collection().find_one({"email_key": email_key})
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

        # Store identity event -- usa el hash de identidad (D-2), no un
        # sha256 sin sal sobre RUT+email en texto plano
        event = IdentityEvent(
            user_id=rut_key,
            event_type="rut_email",
            hash_value=generate_short_hash(rut_key + email_key),
            verifier="dao_ciudadana_registration"
        )
        await identity_events_collection().insert_one(event.model_dump())

        logger.info(f"New user registered (rut_key={rut_key[:8]}...)")

        return UserResponse(
            ok=True,
            user_id=user.id,
            rut=formatted_rut,
            email=normalized_email,
            nombre=request.nombre,
            subject_id=f"rut:{rut_key}",
            assurance_level="AL1"  # Lower assurance since not verified with ClaveÚnica
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
        rut_key = lookup_key(formatted_rut, domain="rut")
        email_key = lookup_key(normalized_email, domain="email")

        user_doc = await users_collection().find_one({
            "rut_key": rut_key,
            "email_key": email_key,
        })

        if not user_doc:
            return UserResponse(ok=False, error="RUT o email incorrectos")

        if user_doc.get("status") != "active":
            return UserResponse(ok=False, error="Cuenta desactivada")

        event = IdentityEvent(
            user_id=rut_key,
            event_type="rut_email_login",
            hash_value=generate_short_hash(f"login_{rut_key}"),
            verifier="dao_ciudadana_login"
        )
        await identity_events_collection().insert_one(event.model_dump())

        logger.info(f"User logged in (rut_key={rut_key[:8]}...)")

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
            subject_id=f"rut:{rut_key}",
            assurance_level="AL1"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in login: {e}")
        return UserResponse(ok=False, error="No se pudo iniciar sesión. Intenta de nuevo.")

