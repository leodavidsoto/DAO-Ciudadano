"""
Authentication Service
Business logic for identity verification and authentication
"""
from typing import Optional, Tuple
import uuid
import base64
import logging
from PIL import Image
import io

from ..core.security import generate_short_hash
from ..core.errors import report
from ..core.database import identity_events_collection
from ..core.config import settings
from ..models import IdentityEvent

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling authentication operations"""
    
    @staticmethod
    async def verify_clave_unica(rut: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Verify user with ClaveÚnica
        Returns: (success, subject_id, assurance_level, error)
        """
        if not rut or len(rut) < 8:
            return (False, None, None, "RUT inválido")
        
        try:
            # Mock successful authentication
            # TODO: Integrate with real ClaveÚnica OAuth
            subject_id = f"claveunica:{rut}"
            
            # Store identity event
            event = IdentityEvent(
                user_id=rut,
                event_type="clave_unica",
                hash_value=generate_short_hash(rut),
                verifier="claveunica_gov"
            )
            await identity_events_collection().insert_one(event.model_dump())
            
            return (True, subject_id, "AL2", None)
            
        except Exception as e:
            logger.error(f"ClaveÚnica verification error: {e}")
            return (False, None, None, report(e, "auth_service"))
    
    @staticmethod
    async def verify_nfc() -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Verify Chilean ID card NFC chip
        Returns: (success, chip_serial, doc_hash, error)
        """
        try:
            # Mock successful NFC reading
            # TODO: Integrate with real NFC reader SDK
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
            
            return (True, chip_serial, doc_hash, None)
            
        except Exception as e:
            logger.error(f"NFC verification error: {e}")
            return (False, None, None, report(e, "auth_service"))
    
    @staticmethod
    async def analyze_liveness(image_data: bytes) -> Tuple[bool, Optional[float], Optional[str], Optional[str]]:
        """
        Analyze image for liveness detection
        Returns: (success, score, analysis, error)
        """
        if len(image_data) > 10 * 1024 * 1024:  # 10MB limit
            return (False, None, None, "Imagen muy grande (máximo 10MB)")
        
        try:
            # Validate image
            image = Image.open(io.BytesIO(image_data))
            image.verify()
        except Exception:
            return (False, None, None, "Imagen inválida")
        
        try:
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Fail CLOSED (audit finding N-9): without a provider there is no
            # liveness evidence, and inventing a passing score would fabricate
            # identity evidence out of a configuration error.
            api_key = settings.EMERGENT_LLM_KEY
            if not api_key:
                logger.error("EMERGENT_LLM_KEY not configured: liveness cannot run")
                return (False, None, None, "La verificación de vida no está disponible.")

            score, analysis = await AuthService._analyze_with_llm(base64_image, api_key)
            if score is None:
                return (False, None, None, "No se pudo completar la verificación de vida.")
            if score < settings.LIVENESS_MIN_SCORE:
                logger.info(f"Liveness rejected: {score} < {settings.LIVENESS_MIN_SCORE}")
                return (False, score, analysis, "No pudimos confirmar que sea una persona real en vivo.")
            
            # Store identity event
            event = IdentityEvent(
                user_id=generate_short_hash(base64_image[:100]),
                event_type="liveness",
                hash_value=generate_short_hash(f"liveness_{score}"),
                verifier="llm_vision_ai"
            )
            await identity_events_collection().insert_one(event.model_dump())
            
            return (True, score, analysis, None)
            
        except Exception as e:
            logger.error(f"Liveness analysis error: {e}")
            return (False, None, None, report(e, "analyze_liveness"))
    
    @staticmethod
    async def _analyze_with_llm(base64_image: str, api_key: str) -> Tuple[float, str]:
        """Perform LLM-based liveness analysis"""
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
            
            chat = LlmChat(
                api_key=api_key,
                session_id=f"liveness_{uuid.uuid4()}",
                system_message="""Eres un experto en detección de vida (liveness detection). 
                Analiza esta imagen y determina si muestra una persona real en vivo.
                
                Responde con formato: "SCORE: 0.85 | ANÁLISIS: [tu análisis detallado]" """
            ).with_model("openai", "gpt-4o")
            
            image_content = ImageContent(image_base64=base64_image)
            user_message = UserMessage(
                text="Analiza esta imagen para liveness detection.",
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
                except Exception:
                    pass
            
            return (score, analysis)
            
        except ImportError:
            # No provider installed → no evidence. Never a passing score.
            logger.error("emergentintegrations not installed: liveness cannot run")
            return (None, None)
        except Exception as e:
            logger.error(f"Liveness provider error: {e}", exc_info=True)
            return (None, None)


# Singleton instance
auth_service = AuthService()
