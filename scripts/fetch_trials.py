#!/usr/bin/env python3
"""
溃疡性结肠炎（UC）药物临床试验数据自动更新脚本

数据源：ClinicalTrials.gov API v2
文档：https://clinicaltrials.gov/data-api/api
无需认证，速率限制约 50 请求/分钟

功能：
  1. 查询每个药物在 ClinicalTrials.gov 上的最新试验记录
  2. 更新 data.json 中的 nct_id 和 phase 字段
  3. 更新 last_updated 时间戳

注意：
  - 只更新结构化字段，不修改人工整理的 mechanism/notes
  - 查询失败的药物会静默跳过，不影响其他药物
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
import os
import sys
from datetime import datetime, timezone


# ============================================================
# 药物 -> ClinicalTrials.gov 干预措施关键词映射
# key: data.json 中的 name_cn
# value: 用于 API 查询的英文关键词
# ============================================================
DRUG_QUERIES = {
    "Mirikizumab（Omvoh）": "mirikizumab",
    "Etrasimod（Velsipity）": "etrasimod",
    "Guselkumab（Tremfya）": "guselkumab",
    "Upadacitinib（Rinvoq）": "upadacitinib",
    "Filgotinib（Jyseleca）": "filgotinib",
    "Tofacitinib（Xeljanz）": "tofacitinib",
    "Tulisokibart（MK-7240）": "tulisokibart",
    "Duvakitug": "duvakitug",
    "JNJ-2113（Icotrokinra）": "icotrokinra",
    "JNJ-78934804": "JNJ-78934804",
    "XmAb942": "XmAb942",
    "PALI-2108": "PALI-2108",
    "Rosnilimab": "rosnilimab",
}


# ============================================================
# API 配置
# ============================================================
API_BASE = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {
    "User-Agent": "UC-Drug-Pipeline/1.0 (automated weekly update)",
    "Accept": "application/json",
}
CONDITION = "ulcerative colitis"   # 适应症限定
REQUEST_TIMEOUT = 20                # 单次请求超时（秒）
SLEEP_BETWEEN = 0.5                 # 请求间隔（秒），避免触发速率限制


def fetch_trials(intervention: str, condition: str = CONDITION):
    """
    查询指定干预措施 + 适应症的临床试验

    返回：studies 列表（按最后更新日期倒序）
    """
    params = {
        "query.intr": intervention,
        "query.cond": condition,
        "pageSize": 5,
        "sort": "LastUpdatePostDate:desc",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,LastUpdatePostDate",
        "format": "json",
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
        return data.get("studies", [])
    except urllib.error.HTTPError as e:
        print(f"    [HTTP {e.code}] {intervention}")
        return []
    except urllib.error.URLError as e:
        print(f"    [URL Error] {intervention}: {e.reason}")
        return []
    except Exception as e:
        print(f"    [WARN] {intervention}: {e}")
        return []


def normalize_phase(phases):
    """
    将 API 返回的 phase 列表转换为中文/英文状态

    API 返回值示例：["PHASE3"] / ["PHASE2", "PHASE3"] / [] / None
    """
    if not phases:
        return None, None

    p = phases[0] if isinstance(phases, list) else phases
    mapping = {
        "PHASE3": ("III期", "Phase III"),
        "PHASE2": ("II期", "Phase II"),
        "PHASE1": ("I期", "Phase I"),
        "EARLY_PHASE1": ("早期I期", "Early Phase I"),
        "PHASE4": ("IV期", "Phase IV"),
    }
    return mapping.get(p, (None, None))


def extract_latest(studies):
    """
    从 studies 列表中提取最新一条的关键字段

    返回：dict 或 None
    """
    if not studies:
        return None

    latest = studies[0]
    protocol = latest.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status_mod = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})

    return {
        "nct_id": ident.get("nctId", ""),
        "title": ident.get("briefTitle", ""),
        "status": status_mod.get("overallStatus", ""),
        "phases": design.get("phases", []),
        "last_update": status_mod.get("lastUpdatePostDateStruct", {}).get("date", ""),
    }


def main():
    # ---------- 定位 data.json ----------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(script_dir, "..", "data.json")
    data_path = os.path.abspath(data_path)

    if not os.path.exists(data_path):
        print(f"[ERROR] data.json not found at: {data_path}")
        sys.exit(1)

    print(f"[INFO] Loading: {data_path}")
    with open(data_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    drugs = dataset.get("drugs", [])
    print(f"[INFO] Total drugs: {len(drugs)}")

    updated_count = 0
    queried_count = 0

    # ---------- 逐个查询 ----------
    for drug in drugs:
        cn_name = drug.get("name_cn", "")
        if cn_name not in DRUG_QUERIES:
            print(f"[SKIP] {cn_name} (no query mapping)")
            continue

        intervention = DRUG_QUERIES[cn_name]
        print(f"\n[QUERY] {cn_name}  ->  '{intervention}'")

        studies = fetch_trials(intervention)
        queried_count += 1

        if not studies:
            print(f"    No results found")
            time.sleep(SLEEP_BETWEEN)
            continue

        info = extract_latest(studies)
        if not info:
            time.sleep(SLEEP_BETWEEN)
            continue

        print(f"    NCT: {info['nct_id']}")
        print(f"    Status: {info['status']}")
        print(f"    Phase: {info['phases']}")
        print(f"    Last update: {info['last_update']}")

        # ---------- 更新 NCT ID ----------
        if info["nct_id"] and not drug.get("nct_id"):
            drug["nct_id"] = info["nct_id"]
            print(f"    -> nct_id updated")
            updated_count += 1

        # ---------- 更新 phase（仅当 API 有明确阶段） ----------
        phase_cn, phase_en = normalize_phase(info["phases"])
        if phase_cn:
            current = drug.get("phase", "")
            # 保留人工判断的修饰（失败/终止/拒批等）
            if any(kw in current for kw in ["失败", "终止", "拒批", "未达", "不一致"]):
                print(f"    -> phase kept (manual override): {current}")
            elif phase_cn != current:
                drug["phase"] = phase_cn
                drug["phase_en"] = phase_en
                print(f"    -> phase updated: {current} -> {phase_cn}")
                updated_count += 1

        time.sleep(SLEEP_BETWEEN)

    # ---------- 更新时间戳 ----------
    dataset["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"[DONE] Queried: {queried_count}  |  Fields updated: {updated_count}")
    print(f"[DONE] Last updated: {dataset['last_updated']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
