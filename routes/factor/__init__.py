# -*- coding: utf-8 -*-
"""
routes/factor/ -- 因子库路由包

三层结构：
  因子库 -> 因子构建/因子评价/多因子/因子挖掘
  因子挖掘 -> GP/RL/LLM-GP/SVD/ML
"""
from fastapi import APIRouter

from routes.factor.library import router as _library_router
from routes.factor.evaluation import router as _evaluation_router
from routes.factor.multifactor import router as _multifactor_router
from routes.factor.mining.common import router as _mining_common_router
from routes.factor.mining.llm_gp import router as _llm_gp_router
from routes.factor.mining.svd import router as _svd_router
from routes.factor.mining.ml import router as _ml_router
from routes.factor.mining.gp import router as _gp_router
from routes.factor.mining.rl import router as _rl_router
from routes.factor.mining.quant_gp import router as _quant_gp_router

router = APIRouter()
router.include_router(_library_router)
router.include_router(_evaluation_router)
router.include_router(_multifactor_router)
router.include_router(_mining_common_router)
router.include_router(_llm_gp_router)
router.include_router(_svd_router)
router.include_router(_ml_router)
router.include_router(_gp_router)
router.include_router(_rl_router)
router.include_router(_quant_gp_router)
