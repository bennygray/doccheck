"""L1 - image_impl/hamming_comparator (C13)

hamming 用 imagehash 真实 API;_compare_pair 纯函数可直接测(不查 DB)。
"""

from __future__ import annotations

import imagehash
import pytest

from app.services.detect.agents.image_impl.config import ImageReuseConfig
from app.services.detect.agents.image_impl import hamming_comparator


def _hex(base: str = "0000000000000000") -> str:
    """生成 16-char hex(pad/trim)。"""
    return base.ljust(16, "0")[:16]


def test_md5_byte_match_hit() -> None:
    """同 md5 → byte_match。"""
    cfg = ImageReuseConfig(phash_distance_threshold=5)
    imgs_a = [(1, 11, "abc123", _hex("ff"), "body")]
    imgs_b = [(2, 22, "abc123", _hex("00"), "body")]
    md5, phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert len(md5) == 1
    assert md5[0]["hit_strength"] == 1.0
    assert md5[0]["match_type"] == "byte_match"
    # MD5 命中去重:不进 pHash 路
    assert phash == []


def test_phash_close_distance() -> None:
    """无 md5 碰撞,phash 相近 → visual_similar。"""
    cfg = ImageReuseConfig(phash_distance_threshold=5)
    h_a = _hex("ffff000000000000")
    h_b = _hex("fffe000000000000")  # 差 1 bit
    imgs_a = [(1, 11, "md5a", h_a, "body")]
    imgs_b = [(2, 22, "md5b", h_b, "body")]
    md5, phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert md5 == []
    assert len(phash) == 1
    assert phash[0]["distance"] == 1
    assert phash[0]["match_type"] == "visual_similar"


def test_phash_distance_above_threshold() -> None:
    """phash 距离超阈值 → 不命中。"""
    cfg = ImageReuseConfig(phash_distance_threshold=2)
    h_a = _hex("ff00000000000000")
    h_b = _hex("00ff000000000000")  # 差较大
    imgs_a = [(1, 11, "md5a", h_a, "body")]
    imgs_b = [(2, 22, "md5b", h_b, "body")]
    md5, phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert md5 == []
    # 差距远超 2
    assert all(p["distance"] <= 2 for p in phash) or phash == []


def test_md5_exact_match_priority() -> None:
    """同对图 md5 命中后不进 phash 路(去重)。"""
    cfg = ImageReuseConfig(phash_distance_threshold=64)  # 宽松
    h = _hex("ff")
    imgs_a = [(1, 11, "same", h, None)]
    imgs_b = [(2, 22, "same", h, None)]  # md5 + phash 全命中
    md5, phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert len(md5) == 1
    # 同对 (1, 2) 在 phash 路被跳过
    assert all(
        not (p["doc_id_a"] == 11 and p["doc_id_b"] == 22) for p in phash
    )


def test_hamming_imagehash_api() -> None:
    """验证 imagehash.hex_to_hash(a) - hex_to_hash(b) 给出 Hamming 距离。"""
    a = imagehash.hex_to_hash(_hex("ffff000000000000"))
    b = imagehash.hex_to_hash(_hex("ffff000000000000"))
    assert a - b == 0
    c = imagehash.hex_to_hash(_hex("fffe000000000000"))
    assert abs(a - c) == 1


def test_hit_strength_formula() -> None:
    cfg = ImageReuseConfig(phash_distance_threshold=64)
    imgs_a = [(1, 11, "md5a", _hex("ff00"), None)]
    imgs_b = [(2, 22, "md5b", _hex("fe00"), None)]
    _md5, phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert len(phash) == 1
    d = phash[0]["distance"]
    # hit_strength = 1 - d/64(四舍五入 4 位)
    assert phash[0]["hit_strength"] == round(1.0 - d / 64.0, 4)


def test_empty_inputs_return_empty() -> None:
    cfg = ImageReuseConfig()
    md5, phash = hamming_comparator._compare_pair(1, 2, [], [], cfg)
    assert md5 == []
    assert phash == []


def test_multiple_md5_hits() -> None:
    """多张 md5 相同 → 全部记录。"""
    cfg = ImageReuseConfig(phash_distance_threshold=5)
    imgs_a = [
        (1, 11, "same", _hex("ff"), "body"),
        (2, 11, "another", _hex("aa"), "body"),
    ]
    imgs_b = [
        (10, 22, "same", _hex("ff"), "body"),
        (11, 22, "another", _hex("aa"), "body"),
    ]
    md5, _phash = hamming_comparator._compare_pair(100, 200, imgs_a, imgs_b, cfg)
    assert len(md5) == 2
    assert {m["md5"] for m in md5} == {"same", "another"}


def test_bidder_ids_recorded() -> None:
    cfg = ImageReuseConfig()
    imgs_a = [(1, 11, "x", _hex("ff"), "body")]
    imgs_b = [(2, 22, "x", _hex("ff"), "body")]
    md5, _ = hamming_comparator._compare_pair(500, 600, imgs_a, imgs_b, cfg)
    assert md5[0]["bidder_a_id"] == 500
    assert md5[0]["bidder_b_id"] == 600


@pytest.mark.asyncio
async def test_compare_integrates_load(monkeypatch) -> None:
    """集成:monkeypatch _load_images_per_bidder,验证 compare 跨 bidder 两两。"""
    cfg = ImageReuseConfig(phash_distance_threshold=5, min_width=0, min_height=0)

    async def fake_load(_session, _pid, _cfg):
        return {
            1: [(1, 11, "md5_shared", _hex("ff"), None)],
            2: [(2, 22, "md5_shared", _hex("ff"), None)],
            3: [(3, 33, "md5_other", _hex("aa"), None)],
        }

    monkeypatch.setattr(
        hamming_comparator, "_load_images_per_bidder", fake_load
    )
    result = await hamming_comparator.compare(None, 1, cfg)
    # bidder (1,2) md5 命中 1 次;(1,3) 和 (2,3) 不命中
    assert len(result["md5_matches"]) == 1
