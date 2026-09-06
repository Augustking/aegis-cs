"""
产品专家智能体
专门负责产品信息咨询和推荐
"""

from typing import Dict, List, Any
from langchain_core.messages import HumanMessage, SystemMessage
from .base_agent import BaseAgent
from services.business_data import get_business_data

class ProductAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="产品专家",
            role="产品信息咨询和推荐",
            expertise=["产品规格", "价格比较", "功能特点", "市场分析"]
        )

        self.product_database = get_business_data("product")

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """处理产品相关查询"""
        customer_query = state["customer_query"]
        session_id = state.get("session_id", "default")

        # 对话轮次由 classify / agent 外层节点写入 persisted_dialogue，此处只读 state

        # 获取对话历史上下文（优先 state.persisted_dialogue）
        conversation_context = self._get_conversation_context(session_id, state)

        # 从产品数据库中匹配相关信息
        matched_products = self._match_products(customer_query)
        # 证据上下文：供质检节点做接地质检（grounded judging）
        state["evidence_context"] = matched_products

        # 构建系统提示并增强对话上下文说明
        base_system_prompt = f"""你是{self.name}，专门负责{self.role}。
        你的专业领域包括：{', '.join(self.expertise)}

        请根据客户查询提供专业、详细的产品信息，包括：
        - 产品规格和功能特点
        - 价格区间和性价比分析
        - 适用场景和用户群体
        - 与竞品的对比优势

        回答要专业、准确、有说服力。如果客户询问的产品不在你的知识范围内，请说明并建议联系销售代表获取最新信息。"""

        system_prompt = self._enhance_system_prompt_with_context(base_system_prompt)

        # 构建消息列表
        messages = []

        # 添加对话历史上下文（如果有的话）
        if conversation_context:
            context_message = f"""对话历史上下文：
{conversation_context}

请基于以上对话历史和当前查询，提供连贯的回答。"""
            messages.append(SystemMessage(content=context_message))

        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))

        # 如果有匹配的产品信息，添加到上下文中
        if matched_products:
            product_context = f"""产品信息：
{matched_products}

当前查询：{customer_query}"""
            messages.append(HumanMessage(content=product_context))
        else:
            messages.append(HumanMessage(content=customer_query))

        # 调用LLM
        try:
            response = self.llm.invoke(messages)
            response_content = response.content
        except Exception as e:
            print(f"产品专家调用LLM时出错: {e}")
            response_content = "抱歉，处理您的产品查询时遇到技术问题，请稍后重试。"

        # 更新状态
        state["response"] = response_content
        state["current_agent"] = self.name
        state["tools_used"].append(f"{self.name}_processing")

        return state

    def _match_products(self, query: str) -> str:
        """匹配查询中的产品信息"""
        query_lower = query.lower()
        matched_info = []

        # 精确匹配产品名称
        for product_name, product_info in self.product_database.items():
            if product_name in query_lower:
                # 格式化产品信息
                info_text = f"""产品：{product_name}
品牌：{product_info['品牌']}
型号：{', '.join(product_info['型号'])}
价格区间：{product_info['价格区间']}
主要特点：{', '.join(product_info['主要特点'])}
适用人群：{product_info['适用人群']}
推荐指数：{product_info['推荐指数']}"""
                matched_info.append(info_text)

        # 如果没有精确匹配，尝试模糊匹配
        if not matched_info:
            for product_name, product_info in self.product_database.items():
                # 检查查询中是否包含产品相关的关键词
                if any(keyword in query_lower for keyword in ["手机", "电脑", "耳机", "平板", "产品"]):
                    if product_name not in [info.split('：')[1] for info in matched_info]:
                        info_text = f"""相关产品：{product_name}
品牌：{product_info['品牌']}
价格区间：{product_info['价格区间']}
主要特点：{', '.join(product_info['主要特点'][:2])}..."""
                        matched_info.append(info_text)

        return "\n\n".join(matched_info) if matched_info else ""
