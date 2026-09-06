"""
技术支持专家智能体
专门负责技术问题诊断和解决
"""

from typing import Dict, List, Any
from langchain_core.messages import HumanMessage, SystemMessage
from .base_agent import BaseAgent
from services.business_data import get_business_data

class TechAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="技术支持专家",
            role="技术问题诊断和解决",
            expertise=["故障诊断", "系统优化", "软件配置", "硬件维修"]
        )

        self.tech_database = get_business_data("tech")

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """处理技术支持查询"""
        customer_query = state["customer_query"]
        session_id = state.get("session_id", "default")

        # 对话轮次由 classify / 外层节点写入 persisted_dialogue
        conversation_context = self._get_conversation_context(session_id, state)

        # 从技术数据库中匹配相关信息
        matched_info = self._match_tech_info(customer_query)

        # 构建系统提示并增强对话上下文说明
        base_system_prompt = f"""你是{self.name}，专门负责{self.role}。
        你的专业领域包括：{', '.join(self.expertise)}

        请根据客户的技术问题提供专业的解决方案：
        1. 仔细分析问题的技术细节
        2. 提供清晰的解决步骤
        3. 说明可能的原因和预防措施
        4. 如果问题复杂，建议联系专业技术人员

        回答要专业、准确，技术术语要通俗易懂。如果问题超出你的专业范围，请说明并建议转接给相应的技术专家。"""

        system_prompt = self._enhance_system_prompt_with_context(base_system_prompt)

        # 构建消息列表
        messages = []

        # 添加对话历史上下文（如果有的话）
        if conversation_context:
            context_message = f"""对话历史上下文：
{conversation_context}

请基于以上对话历史和当前查询，提供连贯的解答。"""
            messages.append(SystemMessage(content=context_message))

        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))

        # 如果有匹配的技术信息，添加到上下文中
        if matched_info:
            tech_context = f"""技术解决方案：
{matched_info}

当前查询：{customer_query}"""
            messages.append(HumanMessage(content=tech_context))
        else:
            messages.append(HumanMessage(content=customer_query))

        # 调用LLM
        try:
            response = self.llm.invoke(messages)
            response_content = response.content
        except Exception as e:
            print(f"技术专家调用LLM时出错: {e}")
            response_content = "抱歉，处理您的技术问题时遇到系统错误，请稍后重试。"

        state["response"] = response_content
        state["current_agent"] = self.name
        state["tools_used"].append(f"{self.name}_processing")

        return state

    def _match_tech_info(self, query: str) -> str:
        """匹配查询中的技术信息"""
        query_lower = query.lower()
        matched_info = []

        # 精确匹配技术类型
        for category, solutions in self.tech_database.items():
            if any(keyword in query_lower for keyword in category.lower().split()):
                # 格式化技术信息
                info_text = f"""【{category}】\n"""
                for issue, solution in solutions.items():
                    info_text += f"• {issue}：{solution}\n"
                matched_info.append(info_text)

        # 如果没有精确匹配，尝试关键词匹配
        if not matched_info:
            for category, solutions in self.tech_database.items():
                if any(keyword in query_lower for keyword in ["问题", "故障", "无法", "怎么", "怎么办", "技术支持"]):
                    info_text = f"""相关解决方案：{category}\n"""
                    # 只显示前2项解决方案
                    for i, (issue, solution) in enumerate(solutions.items()):
                        if i < 2:
                            info_text += f"• {issue}：{solution}\n"
                    info_text += "..."
                    matched_info.append(info_text)

        return "\n".join(matched_info) if matched_info else ""
