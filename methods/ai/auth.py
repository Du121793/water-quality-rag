import jwt
from fastapi import HTTPException, Request, status

from methods.config.settings import settings


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


async def resolve_web_user_id(request: Request, fallback_user_id: int | None = None) -> int:
    """解析前端或後端傳入的使用者身分。"""

    token = _extract_bearer_token(request)

    if token and settings.web_jwt_secret:
        try:
            decode_kwargs = {
                "algorithms": ["HS256"],
                "options": {"verify_aud": bool(settings.expected_jwt_audience)},
            }
            if settings.expected_jwt_issuer:
                decode_kwargs["issuer"] = settings.expected_jwt_issuer
            if settings.expected_jwt_audience:
                decode_kwargs["audience"] = settings.expected_jwt_audience

            payload = jwt.decode(token, settings.web_jwt_secret, **decode_kwargs)
            user_id = payload.get("user_id")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="JWT ?? user_id?",
                )
            return int(user_id)
        except jwt.PyJWTError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"JWT ????: {err}",
            ) from err

    if settings.allow_dev_auth_bypass and fallback_user_id is not None:
        return int(fallback_user_id)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少有效身分資訊，請提供 Bearer Token，或在開發模式下傳入 fallback user_id。",
    )
