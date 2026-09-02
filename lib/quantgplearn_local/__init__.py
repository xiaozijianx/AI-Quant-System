# -*- coding: utf-8 -*-
# QuantGplearn 本地化复制包: 仅含本项目实际用到的 8 个文件
# (gpu_transformer / evaluator / tensor_fitness / tensor_data / torch_functions / _program / functions / utils)
# 原版 third_party/QuantGplearn 保留作对照基线; 本地包在原版基础上做 B 档功能扩展。
# 方案详见 docs/QuantGP页面增强功能梳理.md 3.6
__version__ = '1.0.0'

__all__ = ['GpuSymbolicTransformer']

try:
    from .gpu_transformer import GpuSymbolicTransformer
except Exception:
    GpuSymbolicTransformer = None

__all__ = ['GpuSymbolicTransformer']
