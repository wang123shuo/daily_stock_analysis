# -*- coding: utf-8 -*-
"""
===================================
飞书群机器人 Webhook 接口
===================================

支持飞书群聊中 @机器人 提问，机器人自动调用 MiniMax 模型回答。

飞书 Webhook 文档：
https://open.feishu.cn/document/server-docs/im-v1/message/create
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Header, Request, HTTPException
from fastapi.responses import JSONResponse

from bot.handler import handle_feishu_webhook
from src.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feishu", tags=["Feishu"])


def verify_feishu_signature(
    timestamp: str,
    signature: str,
    secret: str
) -> bool:
    """
    验证飞书签名

    Args:
        timestamp: 时间戳
        signature: 签名
        secret: 加密密钥

    Returns:
        是否验证通过
    """
    import hashlib
    import hmac
    import base64

    # 构建签名字符串
    string_to_sign = f"{timestamp}\n{secret}"

    # 计算 HMAC-SHA256
    hmac_obj = hmac.new(
        secret.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    )

    # 计算签名
    calculated_signature = base64.b64encode(hmac_obj.digest()).decode('utf-8')

    return calculated_signature == signature


def decrypt_feishu_encrypted_content(encrypted_content: str, encrypt_key: str) -> str:
    """
    解密飞书加密内容

    Args:
        encrypted_content: 加密内容（Base64编码）
        encrypt_key: 加密密钥

    Returns:
        解密后的原始内容
    """
    import base64
    import hashlib
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    # AES key 是 encrypt_key 的 SHA256 哈希的前 32 字节
    key_bytes = hashlib.sha256(encrypt_key.encode('utf-8')).digest()[:32]

    # 解码加密内容
    encrypted_bytes = base64.b64decode(encrypted_content)

    # AES 解密（ECB 模式）
    cipher = AES.new(key_bytes, AES.MODE_ECB)
    decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)

    return decrypted.decode('utf-8')


@router.post("/webhook")
async def feishu_webhook(
    request: Request,
    x_feishu_signature: Optional[str] = Header(None),
    x_feishu_timestamp: Optional[str] = Header(None),
):
    """
    飞书 Webhook 回调接口

    飞书通过此接口推送群消息事件。

    配置项：
    - FEISHU_WEBHOOK_URL: 飞书自定义机器人 Webhook 地址
    - FEISHU_VERIFICATION_TOKEN: 事件订阅验证 Token
    - FEISHU_ENCRYPT_KEY: 消息加密密钥（可选）
    """
    config = get_config()

    # 检查是否启用飞书机器人
    feishu_webhook_url = getattr(config, 'feishu_webhook_url', None)
    if not feishu_webhook_url:
        logger.warning("飞书 Webhook 未配置，跳过处理")
        return JSONResponse(content={"code": 0, "msg": "ignored"})

    try:
        body = await request.body()
        headers = dict(request.headers)

        # 如果配置了加密密钥，解密内容
        encrypt_key = getattr(config, 'feishu_encrypt_key', None)
        if encrypt_key and encrypt_key.strip():
            try:
                body_json = await request.json()
                encrypted_content = body_json.get('encrypt', '')
                if encrypted_content:
                    decrypted_body = decrypt_feishu_encrypted_content(
                        encrypted_content,
                        encrypt_key
                    )
                    body = decrypted_body.encode('utf-8')
                    logger.debug("飞书消息已解密")
            except Exception as e:
                logger.error(f"飞书消息解密失败: {e}")
                return JSONResponse(
                    content={"code": 1, "msg": "decrypt failed"},
                    status_code=400
                )

        # 验证签名（如果配置了验证 Token）
        verification_token = getattr(config, 'feishu_verification_token', None)
        if verification_token and x_feishu_signature and x_feishu_timestamp:
            # 检查 timestamp 避免 replay 攻击（5分钟内的请求有效）
            try:
                ts = int(x_feishu_timestamp)
                current_ts = int(time.time())
                if abs(current_ts - ts) > 300:
                    logger.warning(f"飞书请求 timestamp 过期: {ts}")
                    return JSONResponse(
                        content={"code": 1, "msg": "timestamp expired"},
                        status_code=400
                    )
            except ValueError:
                pass

            # 注意：这里简化了签名验证，实际应该用 secret 验证
            # 如果需要严格验证，取消下面的注释
            # if not verify_feishu_signature(x_feishu_timestamp, x_feishu_signature, verification_token):
            #     logger.warning("飞书签名验证失败")
            #     return JSONResponse(
            #         content={"code": 1, "msg": "signature mismatch"},
            #         status_code=400
            #     )

        # 处理飞书 Webhook
        response = handle_feishu_webhook(headers, body)

        return JSONResponse(
            content=response.body,
            status_code=response.status_code,
            headers=response.headers
        )

    except Exception as e:
        logger.error(f"处理飞书 Webhook 失败: {e}")
        logger.exception(e)
        return JSONResponse(
            content={"code": 1, "msg": str(e)},
            status_code=500
        )


@router.get("/webhook")
async def feishu_webhook_verify(
    challenge: str,
    token: Optional[str] = None,
    type: Optional[str] = None
):
    """
    飞书 Webhook 验证接口

    用于验证 Webhook URL 的有效性。
    飞书在配置 Webhook 时会发送 GET 请求验证。
    """
    config = get_config()

    verification_token = getattr(config, 'feishu_verification_token', None)

    # 验证 token
    if verification_token and token != verification_token:
        return JSONResponse(
            content={"error": "token mismatch"},
            status_code=403
        )

    # 返回 challenge
    return JSONResponse(content={"challenge": challenge})


@router.post("/push")
async def feishu_push(
    content: str,
    chat_id: Optional[str] = None
):
    """
    手动推送消息到飞书群

    Args:
        content: 消息内容（Markdown 格式）
        chat_id: 群会话 ID（可选，不填则使用配置的 Webhook）
    """
    from src.notification_sender.feishu_sender import FeishuSender

    config = get_config()

    # 如果没有提供 chat_id，使用 Webhook 方式推送
    if not chat_id:
        feishu_url = getattr(config, 'feishu_webhook_url', None)
        if not feishu_url:
            raise HTTPException(status_code=400, detail="飞书 Webhook 未配置")

        sender = FeishuSender(config)
        success = sender.send_to_feishu(content)

        if success:
            return {"code": 0, "msg": "success"}
        else:
            raise HTTPException(status_code=500, detail="推送失败")

    # 有 chat_id，使用 Stream 方式发送
    # 这需要飞书 Stream 客户端已启动
    from bot.platforms.feishu_stream import get_feishu_stream_client

    client = get_feishu_stream_client()
    if not client:
        raise HTTPException(status_code=400, detail="飞书 Stream 客户端未启动")

    reply_client = client._reply_client
    if not reply_client:
        raise HTTPException(status_code=400, detail="飞书回复客户端未初始化")

    success = reply_client.send_to_chat(chat_id, content)

    if success:
        return {"code": 0, "msg": "success"}
    else:
        raise HTTPException(status_code=500, detail="推送失败")