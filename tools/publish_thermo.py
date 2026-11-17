"""把 data/temperature.csv 转成微信小程序数据包，可选上传到腾讯云 COS。

小程序端不直连 GitHub（raw.githubusercontent.com 无法加入 request 合法域名），
只读 COS 上的 thermo/data.json。本脚本由 .github/workflows/daily.yml 在每日算完温度后调用。

用法：
    python tools/publish_thermo.py                    # 只构建，打印摘要
    python tools/publish_thermo.py --out /tmp/t.json   # 构建并写文件
    python tools/publish_thermo.py --upload            # 构建并上传 COS
    python tools/publish_thermo.py --upload --key thermo/data.json

上传所需环境变量：COS_BUCKET / COS_REGION / COS_SECRET_ID / COS_SECRET_KEY
"""

import argparse
import csv
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data", "temperature.csv")
DEFAULT_KEY = "thermo/data.json"

FACTORS = [
    ("erp", "股权风险溢价 ERP"),
    ("dy_spread", "股债利差(股息率-10Y)"),
    ("y10", "10Y国债收益率"),
    ("y10_omo", "10Y-7天逆回购"),
    ("credit", "信用利差"),
    ("grade", "等级利差 AA+-AAA"),
    ("cb_premium", "转股溢价率"),
    ("fund_3y", "偏债混基3年年化"),
]
ASSETS = [("stock", "股票"), ("bond", "纯债"), ("cb", "转债"), ("mr", "均值回归(偏债混基)")]
REGIME_ORDER = ["极冷", "偏冷", "中性", "偏热", "过热"]


def num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def r1(v):
    return None if v is None else round(v, 1)


def build(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        sys.exit("[错误] temperature.csv 为空")
    date_col = rows[0].keys().__iter__().__next__()
    for k in rows[0].keys():
        if k.strip() == "" or k.lower() in ("date", "日期", "trade_date"):
            date_col = k
            break

    valid = [r for r in rows if num(r.get("composite")) is not None]
    if not valid:
        sys.exit("[错误] temperature.csv 中没有可用的 composite 行")

    last = valid[-1]
    prev = valid[-21] if len(valid) >= 21 else None

    hist = [
        {
            "d": r[date_col],
            "c": r1(num(r.get("composite"))),
            "s": r1(num(r.get("stock"))),
            "b": r1(num(r.get("bond"))),
            "cb": r1(num(r.get("cb"))),
            "mr": r1(num(r.get("mr"))),
            "sp": r1(num(r.get("stock_minus_bond"))),
        }
        for r in valid
    ]

    regime = (last.get("regime") or "").strip()
    return {
        "updated": last[date_col],
        "prevDate": prev[date_col] if prev else None,
        "prevComposite": r1(num(prev["composite"])) if prev else None,
        "latest": {
            "composite": r1(num(last["composite"])),
            "regime": regime,
            "nFactors": int(num(last.get("n_factors")) or 0),
            "spread": r1(num(last.get("stock_minus_bond"))),
            "assets": [{"key": k, "name": n, "t": r1(num(last.get(k)))} for k, n in ASSETS],
            "factors": [
                {"key": k, "name": n, "raw": num(last.get("F_" + k)), "t": r1(num(last.get("T_" + k)))}
                for k, n in FACTORS
            ],
        },
        "hist": hist,
    }


def upload(payload, key):
    from qcloud_cos import CosConfig, CosS3Client

    bucket = os.environ.get("COS_BUCKET", "").strip()
    region = os.environ.get("COS_REGION", "").strip() or "ap-shanghai"
    sid = os.environ.get("COS_SECRET_ID", "").strip()
    skey = os.environ.get("COS_SECRET_KEY", "").strip()
    missing = [n for n, v in (("COS_BUCKET", bucket), ("COS_SECRET_ID", sid), ("COS_SECRET_KEY", skey)) if not v]
    if missing:
        sys.exit("[错误] 缺少环境变量: " + ", ".join(missing))

    client = CosS3Client(CosConfig(Region=region, SecretId=sid, SecretKey=skey))
    body = payload.encode("utf-8")
    for attempt in range(1, 4):
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="application/json; charset=utf-8",
                CacheControl="max-age=300",
            )
            print("上传成功 https://%s.cos.%s.myqcloud.com/%s (%d 字节)" % (bucket, region, key, len(body)))
            return
        except Exception as exc:
            print("[第 %d 次] 上传失败: %s" % (attempt, exc), file=sys.stderr)
            if attempt == 3:
                raise
            time.sleep(5 * attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_PATH, help="temperature.csv 路径")
    ap.add_argument("--out", help="把 JSON 写到指定路径（默认不落盘）")
    ap.add_argument("--upload", action="store_true", help="上传到 COS")
    ap.add_argument("--key", default=DEFAULT_KEY, help="COS 对象 key，默认 " + DEFAULT_KEY)
    args = ap.parse_args()

    with open(args.csv, encoding="utf-8-sig") as f:
        data = build(f.read())

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lat = data["latest"]
    print(
        "%s 综合温度=%s %s | 股票=%s 纯债=%s 转债=%s 均值回归=%s | 历史=%d 期 | 包体=%.1f KB"
        % (
            data["updated"],
            lat["composite"],
            lat["regime"] or "-",
            *(a["t"] for a in lat["assets"]),
            len(data["hist"]),
            len(payload.encode("utf-8")) / 1024,
        )
    )

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print("已写入 " + args.out)

    if args.upload:
        upload(payload, args.key)


if __name__ == "__main__":
    main()
