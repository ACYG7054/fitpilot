"""把内置的演示语料写入示例知识库。"""

import asyncio

from app.core.config import get_settings
from app.models.api import KnowledgeDocumentIn
from app.services.chroma_service import ChromaService
from app.services.openai_service import OpenAIService
from app.services.rag_service import RagService


DEMO_DOCUMENTS = [
    KnowledgeDocumentIn(
        document_id="fitness-cn-001",
        title="增肌期蛋白质建议",
        source="fitpilot_demo",
        section="nutrition",
        tags=["增肌", "蛋白质"],
        content=(
            "增肌期蛋白质摄入通常建议为每公斤体重 1.6 到 2.2 克。"
            "如果一天安排了高强度力量训练，蛋白质应均匀分配到三到五餐中，"
            "每餐优先保证高质量蛋白来源，如鸡胸肉、牛肉、鸡蛋、奶制品和乳清蛋白。"
        ),
    ),
    KnowledgeDocumentIn(
        document_id="fitness-cn-002",
        title="减脂期力量训练原则",
        source="fitpilot_demo",
        section="training",
        tags=["减脂", "力量训练"],
        content=(
            "减脂期不应只做有氧训练。为了尽量保留肌肉量，建议继续进行基础力量训练，"
            "优先保留深蹲、硬拉、卧推、划船等复合动作，并在热量缺口过大时适当降低训练总量而不是完全停练。"
        ),
    ),
    KnowledgeDocumentIn(
        document_id="fitness-cn-003",
        title="深蹲动作要点",
        source="fitpilot_demo",
        section="movement",
        tags=["深蹲", "动作"],
        content=(
            "深蹲时应先稳定核心，保持脚掌三点受力，膝盖方向与脚尖方向基本一致。"
            "下蹲过程中优先保证脊柱中立位，避免塌腰或骨盆明显后卷。"
            "如果踝关节活动度不足，可以通过抬高脚跟或专项活动度训练改善动作质量。"
        ),
    ),
    KnowledgeDocumentIn(
        document_id="fitness-cn-004",
        title="训练后恢复建议",
        source="fitpilot_demo",
        section="recovery",
        tags=["恢复", "睡眠"],
        content=(
            "训练后恢复不仅依赖拉伸，还依赖睡眠、营养和训练安排。"
            "大多数力量训练人群应优先保证 7 到 9 小时睡眠，"
            "并在训练后补充蛋白质和碳水化合物以支持糖原恢复和肌肉修复。"
        ),
    ),
]


async def main() -> None:
    """创建相关服务对象，并把内置文档批量导入知识库。"""
    # 这里内置了一小份中文演示语料，便于项目开箱即跑通完整链路。
    settings = get_settings()
    openai_service = OpenAIService(settings)
    chroma_service = ChromaService(settings, openai_service)
    rag_service = RagService(chroma_service, settings)
    count = await rag_service.ingest_documents(DEMO_DOCUMENTS)
    print(f"Seeded {count} knowledge documents into Chroma.")


if __name__ == "__main__":
    asyncio.run(main())
