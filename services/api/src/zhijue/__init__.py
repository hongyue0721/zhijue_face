"""职觉 Demo 后端包。

分层（docs/02-architecture.md §4—§5）：domain 纯逻辑不得 import
FastAPI、openJiuwen 或数据库 ORM；adapters 接 SDK/DB/模型；application
编排端口；api 只做校验与映射。
"""
