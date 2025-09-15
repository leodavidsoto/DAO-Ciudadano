from fastapi import FastAPI, APIRouter, HTTPException, File, UploadFile
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import hashlib
import base64
from PIL import Image
import io
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

class ClaveUnicaRequest(BaseModel):
    rut: str

class ClaveUnicaResponse(BaseModel):
    ok: bool
    subject_id: Optional[str] = None
    assurance_level: Optional[str] = None
    error: Optional[str] = None

class NFCResponse(BaseModel):
    ok: bool
    chip_serial: Optional[str] = None
    doc_hash: Optional[str] = None
    error: Optional[str] = None

class LivenessResponse(BaseModel):
    ok: bool
    score: Optional[float] = None
    analysis: Optional[str] = None
    error: Optional[str] = None

class WalletConnectResponse(BaseModel):
    ok: bool
    address: Optional[str] = None
    error: Optional[str] = None

class MintSBTRequest(BaseModel):
    wallet_address: str
    assurance_level: str
    doc_hash: str

class MintSBTResponse(BaseModel):
    ok: bool
    token_id: Optional[int] = None
    tx_hash: Optional[str] = None
    error: Optional[str] = None

class DashboardStats(BaseModel):
    total_members: int
    recent_joins: int
    your_token_id: Optional[int] = None

class IdentityEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    event_type: str  # "clave_unica", "nfc", "liveness"
    hash_value: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verifier: str

class Member(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet_address: str
    token_id: int
    doc_hash: str
    assurance_level: str
    status: str = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Utility functions
def generate_mock_hash(data: str) -> str:
    """Generate a mock hash for demo purposes"""
    return hashlib.sha256(data.encode()).hexdigest()[:16]

async def sleep_mock(seconds: float):
    """Mock async sleep for demo purposes"""
    import asyncio
    await asyncio.sleep(seconds * 0.1)  # Faster for demo

# Routes
@api_router.get("/")
async def root():
    return {"message": "DAO Citizenship API"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.dict()
    status_obj = StatusCheck(**status_dict)
    await db.status_checks.insert_one(status_obj.dict())
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**status_check) for status_check in status_checks]

@api_router.post("/auth/clave-unica", response_model=ClaveUnicaResponse)
async def authenticate_clave_unica(request: ClaveUnicaRequest):
    """Mock ClaveÚnica authentication"""
    try:
        await sleep_mock(1.2)
        
        if not request.rut or len(request.rut) < 8:
            return ClaveUnicaResponse(ok=False, error="RUT inválido")
        
        # Mock successful authentication
        subject_id = f"claveunica:{request.rut}"
        
        # Store identity event
        event = IdentityEvent(
            user_id=request.rut,
            event_type="clave_unica",
            hash_value=generate_mock_hash(request.rut),
            verifier="claveunica_gov"
        )
        await db.identity_events.insert_one(event.dict())
        
        return ClaveUnicaResponse(
            ok=True,
            subject_id=subject_id,
            assurance_level="AL2"
        )
        
    except Exception as e:
        logging.error(f"Error in ClaveÚnica auth: {e}")
        return ClaveUnicaResponse(ok=False, error=str(e))

@api_router.post("/auth/nfc", response_model=NFCResponse)
async def authenticate_nfc():
    """Mock NFC authentication"""
    try:
        await sleep_mock(1.6)
        
        # Mock successful NFC reading
        chip_serial = f"NFC-CL-CH-{uuid.uuid4().hex[:8].upper()}"
        doc_hash = f"0x{generate_mock_hash('nfc_doc_' + chip_serial)}"
        
        # Store identity event
        event = IdentityEvent(
            user_id=chip_serial,
            event_type="nfc",
            hash_value=doc_hash,
            verifier="chile_gov_nfc"
        )
        await db.identity_events.insert_one(event.dict())
        
        return NFCResponse(
            ok=True,
            chip_serial=chip_serial,
            doc_hash=doc_hash
        )
        
    except Exception as e:
        logging.error(f"Error in NFC auth: {e}")
        return NFCResponse(ok=False, error=str(e))

@api_router.post("/auth/liveness", response_model=LivenessResponse)
async def analyze_liveness(file: UploadFile = File(...)):
    """Real liveness detection using LLM vision"""
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
        
        # Initialize LLM chat for liveness detection
        api_key = os.environ.get('EMERGENT_LLM_KEY')
        if not api_key:
            return LivenessResponse(ok=False, error="API key no configurada")
        
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
        
        # Create image content
        image_content = ImageContent(image_base64=base64_image)
        
        # Send message with image
        user_message = UserMessage(
            text="Analiza esta imagen para detección de vida (liveness detection). ¿Es una persona real tomándose un selfie ahora mismo?",
            file_contents=[image_content]
        )
        
        response = await chat.send_message(user_message)
        
        # Parse response
        score = 0.5  # default
        analysis = response
        
        if "SCORE:" in response:
            try:
                score_part = response.split("SCORE:")[1].split("|")[0].strip()
                score = float(score_part)
                if "|" in response:
                    analysis = response.split("|", 1)[1].replace("ANÁLISIS:", "").strip()
            except:
                pass
        
        # Store identity event
        event = IdentityEvent(
            user_id=generate_mock_hash(base64_image[:100]),
            event_type="liveness",
            hash_value=generate_mock_hash(f"liveness_{score}"),
            verifier="llm_vision_ai"
        )
        await db.identity_events.insert_one(event.dict())
        
        return LivenessResponse(
            ok=True,
            score=score,
            analysis=analysis
        )
        
    except Exception as e:
        logging.error(f"Error in liveness detection: {e}")
        return LivenessResponse(ok=False, error=f"Error en análisis: {str(e)}")

@api_router.post("/wallet/connect", response_model=WalletConnectResponse)
async def connect_wallet():
    """Mock wallet connection"""
    try:
        await sleep_mock(0.8)
        
        # Generate mock wallet address
        address = f"0x{uuid.uuid4().hex[:8].upper()}...C1TY"
        
        return WalletConnectResponse(
            ok=True,
            address=address
        )
        
    except Exception as e:
        logging.error(f"Error connecting wallet: {e}")
        return WalletConnectResponse(ok=False, error=str(e))

@api_router.post("/membership/mint", response_model=MintSBTResponse)
async def mint_sbt(request: MintSBTRequest):
    """Mock SBT minting"""
    try:
        await sleep_mock(1.8)
        
        # Generate mock token ID and transaction hash
        token_id = len(await db.members.find().to_list(1000)) + 1
        tx_hash = f"0xM1NT{uuid.uuid4().hex[:8].upper()}"
        
        # Store member in database
        member = Member(
            wallet_address=request.wallet_address,
            token_id=token_id,
            doc_hash=request.doc_hash,
            assurance_level=request.assurance_level
        )
        await db.members.insert_one(member.dict())
        
        return MintSBTResponse(
            ok=True,
            token_id=token_id,
            tx_hash=tx_hash
        )
        
    except Exception as e:
        logging.error(f"Error minting SBT: {e}")
        return MintSBTResponse(ok=False, error=str(e))

@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        total_members = await db.members.count_documents({"status": "active"})
        
        # Count recent joins (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc).replace(day=1)  # Mock: this month
        recent_joins = await db.members.count_documents({
            "status": "active",
            "created_at": {"$gte": thirty_days_ago}
        })
        
        return DashboardStats(
            total_members=max(total_members, 1432),  # Show at least demo number
            recent_joins=max(recent_joins, 32),
            your_token_id=None
        )
        
    except Exception as e:
        logging.error(f"Error getting dashboard stats: {e}")
        return DashboardStats(total_members=1432, recent_joins=32)

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()