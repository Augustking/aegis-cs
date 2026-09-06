"""
综合客服智能体
专门负责一般咨询处理
"""

from typing import Dict, List, Any
from langchain_core.messages import HumanMessage, SystemMessage
from .base_agent import BaseAgent
from services.business_data import get_business_data

class GeneralAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="综合客服",
            role="一般咨询处理",
            expertise=["信息查询", "基础服务", "问题转接"]
        )

        self.service_database = get_business_data("general")

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """处理一般咨询查询"""
        customer_query = state["customer_query"]
        session_id = state.get("session_id", "default")

        # 对话轮次由 classify / 外层节点写入 persisted_dialogue
        conversation_context = self._get_conversation_context(session_id, state)

        # 从服务数据库中匹配相关信息
        matched_info = self._match_service_info(customer_query)

        # 构建系统提示并增强对话上下文说明
        base_system_prompt = f"""你是{self.name}，专门负责{self.role}。
        你的专业领域包括：{', '.join(self.expertise)}

        请以友好、专业的态度处理客户的一般咨询：
        1. 耐心倾听客户的问题
        2. 提供准确、有用的信息
        3. 如果问题超出你的专业范围，建议转接给相关专家
        4. 确保客户得到满意的答复

        回答要友好、专业，体现良好的服务态度。如果问题复杂或需要专业知识，请说明并建议转接给相应的专业智能体。"""

        system_prompt = self._enhance_system_prompt_with_context(base_system_prompt)

        # 构建消息列表
        messages = []

        # 添加对话历史上下文（如果有的话）
        if conversation_context:
            context_message = f"""对话历史上下文：
{conversation_context}

请基于以上对话历史和当前查询，提供连贯的咨询。"""
            messages.append(SystemMessage(content=context_message))

        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))

        # 如果有匹配的服务信息，添加到上下文中
        if matched_info:
            service_context = f"""服务信息：
{matched_info}

当前查询：{customer_query}"""
            messages.append(HumanMessage(content=service_context))
        else:
            messages.append(HumanMessage(content=customer_query))

        # 调用LLM
        try:
            response = self.llm.invoke(messages)
            response_content = response.content
        except Exception as e:
            print(f"综合客服调用LLM时出错: {e}")
            response_content = "抱歉，处理您的咨询时遇到系统错误，请稍后重试。"

        state["response"] = response_content
        state["current_agent"] = self.name
        state["tools_used"].append(f"{self.name}_processing")

        return state

    def _match_service_info(self, query: str) -> str:
        """匹配查询中的服务信息"""
        query_lower = query.lower()
        matched_info = []

        # 精确匹配服务类型
        for category, services in self.service_database.items():
            if any(keyword in query_lower for keyword in category.lower().split()):
                # 格式化服务信息
                info_text = f"""【{category}】\n"""
                for service, description in services.items():
                    info_text += f"• {service}：{description}\n"
                matched_info.append(info_text)

        # 如果没有精确匹配，尝试关键词匹配
        if not matched_info:
            for category, services in self.service_database.items():
                if any(keyword in query_lower for keyword in ["时间", "联系", "服务", "营业", "电话", "邮箱"]):
                    info_text = f"""相关信息：{category}\n"""
                    # 只显示前2项服务
                    for i, (service, description) in enumerate(services.items()):
                        if i < 2:
                            info_text += f"• {service}：{description}\n"
                    info_text += "..."
                    matched_info.append(info_text)

        return "\n".join(matched_info) if matched_info else ""
