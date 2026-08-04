"""
Custom Exceptions for DAO Ciudadana
Centralized exception handling
"""

from fastapi import HTTPException, status


class DAOException(Exception):
    """Base exception for DAO Ciudadana"""

    def __init__(self, message: str, code: str = "DAO_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(DAOException):
    """Authentication related errors"""

    def __init__(self, message: str = "Error de autenticación"):
        super().__init__(message, "AUTH_ERROR")


class VerificationError(DAOException):
    """Identity verification errors"""

    def __init__(self, message: str = "Error de verificación"):
        super().__init__(message, "VERIFICATION_ERROR")


class WalletError(DAOException):
    """Wallet operation errors"""

    def __init__(self, message: str = "Error de wallet"):
        super().__init__(message, "WALLET_ERROR")


class BlockchainError(DAOException):
    """Blockchain interaction errors"""

    def __init__(self, message: str = "Error de blockchain"):
        super().__init__(message, "BLOCKCHAIN_ERROR")


class MintingError(DAOException):
    """SBT minting errors"""

    def __init__(self, message: str = "Error al mintear SBT"):
        super().__init__(message, "MINTING_ERROR")


class MembershipError(DAOException):
    """Membership related errors"""

    def __init__(self, message: str = "Error de membresía"):
        super().__init__(message, "MEMBERSHIP_ERROR")


# HTTP Exception factory functions
def http_auth_error(detail: str = "No autorizado") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def http_forbidden(detail: str = "Acceso denegado") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def http_not_found(detail: str = "Recurso no encontrado") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def http_bad_request(detail: str = "Solicitud inválida") -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def http_conflict(detail: str = "Conflicto") -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def http_server_error(detail: str = "Error interno del servidor") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail
    )
