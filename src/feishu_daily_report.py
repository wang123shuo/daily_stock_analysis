# -*- coding: utf-8 -*-
"""
===================================
飞书群每日自动推送模块
===================================

支持每日定时推送股票分析报告到飞书群。

配置项：
- FEISHU_DAILY_REPORT_ENABLED: 是否启用每日推送
- FEISHU_DAILY_REPORT_TIME: 推送时间（默认 18:00）
- FEISHU_WEBHOOK_URL: 飞书 Webhook 地址
"""

import logging
from datetime import datetime
from typing import Optional

from src.config import get_config

logger = logging.getLogger(__name__)


class FeishuDailyReporter:
    """
    飞书群每日报告推送器

    在定时任务中调用，自动推送股票分析报告到飞书群。
    """

    def __init__(self, config=None):
        """
        初始化

        Args:
            config: 配置对象（可选，默认从环境变量加载）
        """
        self._config = config or get_config()
        self._enabled = getattr(self._config, 'feishu_daily_report_enabled', False)
        self._schedule_time = getattr(self._config, 'feishu_daily_report_time', "18:00")

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled

    @property
    def schedule_time(self) -> str:
        """获取推送时间"""
        return self._schedule_time

    def send_daily_report(self, report_content: Optional[str] = None) -> bool:
        """
        发送每日报告到飞书群

        Args:
            report_content: 报告内容（如果为 None，自动生成报告）

        Returns:
            是否发送成功
        """
        from src.notification_sender.feishu_sender import FeishuSender

        if not self._enabled:
            logger.info("飞书每日推送未启用，跳过")
            return False

        feishu_url = getattr(self._config, 'feishu_webhook_url', None)
        if not feishu_url:
            logger.warning("飞书 Webhook 未配置，跳过每日推送")
            return False

        try:
            # 生成报告内容
            if report_content is None:
                report_content = self._generate_report()

            # 发送飞书通知
            sender = FeishuSender(self._config)
            success = sender.send_to_feishu(report_content)

            if success:
                logger.info(f"飞书每日报告推送成功")
            else:
                logger.warning(f"飞书每日报告推送失败")

            return success

        except Exception as e:
            logger.error(f"飞书每日报告推送异常: {e}")
            logger.exception(e)
            return False

    def _generate_report(self) -> str:
        """
        生成股票分析报告

        Returns:
            报告内容（Markdown 格式）
        """
        try:
            from src.core.pipeline import StockAnalysisPipeline

            config = self._config

            # 创建分析管道
            pipeline = StockAnalysisPipeline(config)

            # 执行分析
            result = pipeline.run()

            # 获取报告内容
            report = result.get("summary", result.get("brief", "暂无报告内容"))

            # 添加标题和时间
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            header = f"# 📊 A股每日分析报告\n🕐 更新时间: {now}\n\n---\n\n"

            return header + report

        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            return f"⚠️ 报告生成失败: {str(e)}"

    def send_custom_message(self, content: str) -> bool:
        """
        发送自定义消息到飞书群

        Args:
            content: 消息内容

        Returns:
            是否发送成功
        """
        from src.notification_sender.feishu_sender import FeishuSender

        feishu_url = getattr(self._config, 'feishu_webhook_url', None)
        if not feishu_url:
            logger.warning("飞书 Webhook 未配置，跳过消息推送")
            return False

        try:
            sender = FeishuSender(self._config)
            return sender.send_to_feishu(content)
        except Exception as e:
            logger.error(f"飞书消息推送异常: {e}")
            return False


def get_feishu_daily_reporter() -> FeishuDailyReporter:
    """获取飞书每日报告推送器实例"""
    config = get_config()
    return FeishuDailyReporter(config)


def setup_feishu_schedule(scheduler, config=None) -> None:
    """
    设置飞书每日报告定时推送

    Args:
        scheduler: Scheduler 实例
        config: 配置对象（可选）
    """
    config = config or get_config()

    reporter = FeishuDailyReporter(config)

    if not reporter.enabled:
        logger.info("飞书每日推送未启用，跳过调度设置")
        return

    logger.info(f"设置飞书每日推送，执行时间: {reporter.schedule_time}")

    # 添加定时任务
    scheduler.schedule.every().day.at(reporter.schedule_time).do(
        _safe_send_feishu_report
    )


def _safe_send_feishu_report():
    """安全发送飞书报告"""
    try:
        reporter = get_feishu_daily_reporter()
        reporter.send_daily_report()
    except Exception as e:
        logger.error(f"飞书每日推送执行失败: {e}")
        logger.exception(e)