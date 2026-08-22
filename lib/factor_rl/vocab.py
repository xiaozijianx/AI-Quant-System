# -*- coding: utf-8 -*-
"""
lib/factor_rl/vocab.py -- RL 因子挖掘词表 (深度复刻 AlphaMaster model_core/vocab.py)

token id 分段: feature id ∈ [0, F-1], operator id ∈ [F, F+O-1], 两段严格不相交。
VOCAB_VERSION 由有序 token 名称列表确定性派生:
    VOCAB_VERSION = "v" + sha256("\\n".join(token_names)).hexdigest()[:12]
相同有序列表 -> 相同版本; 任意组成/顺序变化 -> 不同版本。
checkpoint 加载时严格校验版本, 不匹配拒绝加载。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .features import FEATURE_NAMES
from .ops import OPERATOR_NAMES


class VocabVersionMismatchError(Exception):
    """加载产物版本 ≠ 当前派生 VOCAB_VERSION"""


def compute_vocab_version(token_names) -> str:
    joined = "\n".join(token_names)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return "v" + digest[:12]


@dataclass(frozen=True)
class FormulaVocab:
    feature_names: tuple
    operator_names: tuple

    @property
    def feature_count(self) -> int:
        return len(self.feature_names)

    @property
    def operator_offset(self) -> int:
        return self.feature_count

    @property
    def token_names(self) -> tuple:
        return self.feature_names + self.operator_names

    @property
    def size(self) -> int:
        return len(self.token_names)

    @property
    def version(self) -> str:
        return compute_vocab_version(self.token_names)

    def verify(self, artifact_version: str) -> None:
        current = self.version
        if artifact_version != current:
            raise VocabVersionMismatchError(
                f"词表版本不匹配: 产物版本 {artifact_version!r} != 当前派生版本 {current!r}"
            )


def _build_formula_vocab() -> FormulaVocab:
    feature_names = tuple(FEATURE_NAMES)
    operator_names = tuple(OPERATOR_NAMES)

    feat_set = set(feature_names)
    op_set = set(operator_names)

    if len(feat_set) != len(feature_names):
        raise ValueError("feature 名称存在重复")
    if len(op_set) != len(operator_names):
        raise ValueError("operator 名称存在重复")
    overlap = feat_set & op_set
    if overlap:
        raise ValueError(f"feature 与 operator 名称冲突: {sorted(overlap)}")

    vocab = FormulaVocab(feature_names=feature_names, operator_names=operator_names)
    if vocab.size != len(feature_names) + len(operator_names):
        raise ValueError("词表计数不一致")
    if len(set(vocab.token_names)) != vocab.size:
        raise ValueError("token 名称存在重复或缺失")
    return vocab


FORMULA_VOCAB = _build_formula_vocab()
FEATURE_NAMES_TUPLE = FORMULA_VOCAB.feature_names
VOCAB_VERSION = FORMULA_VOCAB.version
