# -*- coding: utf-8 -*-
"""
===================================
飞书群聊天命令 - 处理 @机器人 提问
===================================

当用户在飞书群中 @机器人 提问时，直接调用 MiniMax 模型回答。

使用方式：
  @机器人 帮我分析一下茅台最近的走势
  @机器人 今天大盘怎么样
  @机器人 600519 还能买吗
"""

import logging
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.config import get_config

logger = logging.getLogger(__name__)


class FeishuChatCommand(BotCommand):
    """
    飞书群聊天命令 - 处理 @机器人 提问

    当用户在飞书群中 @机器人 时，直接将问题转发给 MiniMax 模型处理。
    无需使用 / 命令前缀。

    使用方式：
      @机器人 帮我分析一下茅台最近的走势
      @机器人 今天大盘怎么样
      @机器人 600519 还能买吗
    """

    @property
    def name(self) -> str:
        return "feishu_chat"

    @property
    def aliases(self) -> List[str]:
        return []  # 无别名，通过 mention 触发

    @property
    def description(self) -> str:
        return "飞书群 @机器人 自由对话（支持股票分析、行情查询）"

    @property
    def usage(self) -> str:
        return "@机器人 <问题>"

    @property
    def hidden(self) -> bool:
        return True  # 不在帮助列表中显示

    def validate_args(self, args: List[str]) -> Optional[str]:
        """验证参数"""
        if not args:
            return "请输入要询问的问题"
        return None

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行飞书聊天命令"""
        config = get_config()

        # 构建用户问题
        user_message = " ".join(args)
        session_id = f"feishu_{message.chat_id}_{message.user_id}"

        logger.info(f"[FeishuChat] User: {message.user_id}, Message: {user_message[:50]}")

        try:
            # 根据配置决定使用 Agent 还是直接的 LLM 调用
            if config.agent_mode:
                # 使用 Agent 模式
                from src.agent.factory import build_agent_executor
                executor = build_agent_executor(config)
                result = executor.chat(message=user_message, session_id=session_id)

                if result.success:
                    return BotResponse.text_response(result.content)
                else:
                    return BotResponse.text_response(f"⚠️ 处理失败: {result.error}")
            else:
                # 直接使用 LLM 回答（不通过 Agent）
                return self._direct_llm_answer(user_message, session_id, config)

        except Exception as e:
            logger.error(f"FeishuChat command failed: {e}")
            logger.exception("FeishuChat error details:")
            return BotResponse.text_response(f"⚠️ 处理出错: {str(e)}")

    def _direct_llm_answer(self, user_message: str, session_id: str, config) -> BotResponse:
        """
        直接调用 LLM 回答问题（不通过 Agent）

        适用于非 Agent 模式下的快速问答。
        """
        try:
            import litellm

            # 确定使用的模型
            model = config.litellm_model
            if not model or model.startswith("__legacy"):
                # 回退到 MiniMax（如果配置了）
                if config.minimax_api_key:
                    model = "minimax/MiniMax-M2.7"
                else:
                    return BotResponse.text_response(
                        "⚠️ 未配置 LLM 模型，无法回答问题。"
                    )

            # 构建消息
            messages = [
                {
                    "role": "system",
                    "content": """你是一个专业的股票分析助手，专门回答用户关于股票分析、行情查询、投资建议等问题。

你的特点是：
1. 专业：提供准确的股票分析和建议
2. 简洁：回答简洁明了，突出重点
3. 谨慎：不推荐具体买卖时机，避免荐股
4. 有用：结合市场趋势、个股走势、技术指标等给出分析

当用户询问股票时，你可以：
- 分析股票走势和趋势
- 提供技术指标参考
- 解答关于股票的问题
- 分析市场热点和板块轮动

请用简洁专业的语言回答。"""
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]

            # 调用 LLM
            logger.info(f"[FeishuChat] Calling LLM: {model}")

            response = litellm.completion(
                model=model,
                messages=messages,
                temperature=config.minimax_temperature if model.startswith("minimax/") else config.openai_temperature,
                api_key=config.minimax_api_key if model.startswith("minimax/") else None,
                api_base=config.minimax_base_url if model.startswith("minimax/") else None,
            )

            answer = response.choices[0].message.content

            return BotResponse.text_response(answer)

        except Exception as e:
            logger.error(f"[FeishuChat] LLM call failed: {e}")
            return BotResponse.text_response(f"⚠️ LLM 调用失败: {str(e)}")


class FeishuBatchReportCommand(BotCommand):
    """
    飞书群推送报告命令 - 手动推送股票分析报告到飞书群

    使用方式：
      /feishu_report     -> 推送完整分析报告
      /feishu_report brief -> 推送简要报告
    """

    @property
    def name(self) -> str:
        return "feishu_report"

    @property
    def aliases(self) -> List[str]:
        return ["飞书报告", "feishu_send"]

    @property
    def description(self) -> str:
        return "手动推送股票分析报告到飞书群"

    @property
    def usage(self) -> str:
        return "/feishu_report [brief|full]"

    @property
    def admin_only(self) -> bool:
        return True  # 仅管理员可用

    def validate_args(self, args: List[str]) -> Optional[str]:
        """验证参数"""
        if args and args[0] not in ["brief", "full", "simple"]:
            return "参数无效，请使用 /feishu_report brief 或 /feishu_report full"
        return None

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行推送报告命令"""
        config = get_config()

        report_type = args[0] if args else "brief"

        logger.info(f"[FeishuReport] User: {message.user_id}, Type: {report_type}")

        try:
            from src.notification_sender.feishu_sender import FeishuSender

            # 获取分析报告
            report_content = self._generate_report(report_type, config)

            # 发送飞书通知
            sender = FeishuSender(config)
            success = sender.send_to_feishu(report_content)

            if success:
                return BotResponse.text_response("✅ 报告已推送到飞书群")
            else:
                return BotResponse.text_response("⚠️ 推送失败，请检查飞书配置")

        except Exception as e:
            logger.error(f"FeishuReport command failed: {e}")
            logger.exception(e)
            return BotResponse.text_response(f"⚠️ 推送出错: {str(e)}")

    def _generate_report(self, report_type: str, config) -> str:
        """生成股票分析报告"""
        try:
            from src.core.pipeline import StockAnalysisPipeline

            pipeline = StockAnalysisPipeline(config)
            result = pipeline.run()

            if report_type == "full":
                return result.get("full_report", result.get("summary", "暂无报告内容"))
            else:
                return result.get("summary", result.get("brief", "暂无报告内容"))

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return f"⚠️ 报告生成失败: {str(e)}"