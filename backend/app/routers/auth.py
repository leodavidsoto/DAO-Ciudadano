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
from ..core.errors import report
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
        return ClaveUnicaResponse(ok=False, error=report(e, "clave_unica"))


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
        return NFCResponse(ok=False, error=report(e, "nfc"))


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
        
        # Fail CLOSED: a liveness check that passes when it cannot run is
        # worse than no check at all — it manufactures identity evidence out
        # of a configuration error (audit finding N-9 / A-3).
        api_key = settings.EMERGENT_LLM_KEY
        if not api_key:
            logger.error("EMERGENT_LLM_KEY not configured: liveness cannot run")
            return LivenessResponse(
                ok=False,
                error="La verificación de vida no está disponible en este momento.",
            )
        # Real liveness analysis via the vision provider
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
            logger.error("emergentintegrations not installed: liveness cannot run")
            return LivenessResponse(
                ok=False,
                error="La verificación de vida no está disponible en este momento.",
            )
        except Exception as e:
            # Never downgrade a provider failure into a passing score.
            logger.error(f"Liveness provider error: {e}", exc_info=True)
            return LivenessResponse(
                ok=False,
                error="No se pudo completar la verificación de vida. Intenta de nuevo.",
            )
    
        # Store identity event
        event = IdentityEvent(
            user_id=generate_short_hash(base64_image[:100]),
            event_type="liveness",
            hash_value=generate_short_hash(f"liveness_{score}"),
            verifier="llm_vision_ai"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        # Threshold enforcement (ROADMAP 1.10): a low score must block the
        # flow, not merely be reported. The frontend advanced on ok=True
        # regardless of the score before this.
        if score < settings.LIVENESS_MIN_SCORE:
            logger.info(f"Liveness rejected: score {score} < {settings.LIVENESS_MIN_SCORE}")
            return LivenessResponse(
                ok=False,
                score=score,
                analysis=analysis,
                error=(
                    "No pudimos confirmar que sea una persona real en vivo. "
                    "Repite la captura con buena luz y mirando a la cámara."
                ),
            )

        return LivenessResponse(
            ok=True,
            score=score,
            analysis=analysis
        )
        
    except Exception as e:
        logger.error(f"Error in liveness detection: {e}")
        return LivenessResponse(ok=False, error=report(e, "liveness"))


# === RUT + Email Authentication (Simple registration while awaiting ClaveÚnica sandbox) ===

from ..models import User, UserRegisterRequest, UserLoginRequest, UserResponse
from ..core.database import users_collection
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
    Validates RUT format and stores user in database.
    """
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
        
        # Check if RUT already registered
        existing = await users_collection().find_one({"rut": formatted_rut})
        if existing:
            return UserResponse(ok=False, error="Este RUT ya está registrado")
        
        # Check if email already registered
        existing_email = await users_collection().find_one({"email": request.email.lower()})
        if existing_email:
            return UserResponse(ok=False, error="Este email ya está registrado")
        
        # Create user
        user = User(
            rut=formatted_rut,
            email=request.email.lower(),
            nombre=request.nombre.strip(),
            apellido=request.apellido.strip()
        )
        
        await users_collection().insert_one(user.model_dump())
        
        # Store identity event
        event = IdentityEvent(
            user_id=formatted_rut,
            event_type="rut_email",
            hash_value=generate_short_hash(formatted_rut + request.email),
            verifier="dao_ciudadana_registration"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        logger.info(f"New user registered: {formatted_rut}")
        
        return UserResponse(
            ok=True,
            user_id=user.id,
            rut=formatted_rut,
            email=request.email.lower(),
            nombre=request.nombre,
            subject_id=f"rut:{formatted_rut}",
            assurance_level="AL1"  # Lower assurance since not verified with ClaveÚnica
        )
        
    except Exception as e:
        logger.error(f"Error in registration: {e}")
        return UserResponse(ok=False, error=report(e, "user_auth"))


@router.post("/login", response_model=UserResponse)
async def login_user(request: UserLoginRequest):
    """
    Login with RUT and email.
    
    Simple authentication for registered users.
    """
    try:
        await mock_delay(0.1)
        
        # Format RUT for lookup
        formatted_rut = format_rut(request.rut)
        
        # Find user
        user_doc = await users_collection().find_one({
            "rut": formatted_rut,
            "email": request.email.lower()
        })
        
        if not user_doc:
            return UserResponse(ok=False, error="RUT o email incorrectos")
        
        if user_doc.get("status") != "active":
            return UserResponse(ok=False, error="Cuenta desactivada")
        
        # Store identity event
        event = IdentityEvent(
            user_id=formatted_rut,
            event_type="rut_email_login",
            hash_value=generate_short_hash(f"login_{formatted_rut}"),
            verifier="dao_ciudadana_login"
        )
        await identity_events_collection().insert_one(event.model_dump())
        
        logger.info(f"User logged in: {formatted_rut}")
        
        return UserResponse(
            ok=True,
            user_id=user_doc.get("id"),
            rut=formatted_rut,
            email=user_doc.get("email"),
            nombre=user_doc.get("nombre"),
            subject_id=f"rut:{formatted_rut}",
            assurance_level="AL1"
        )
        
    except Exception as e:
        logger.error(f"Error in login: {e}")
        return UserResponse(ok=False, error=report(e, "user_auth"))

