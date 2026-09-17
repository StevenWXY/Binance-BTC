"""Build a separate V8 archive view, repairing mark gaps from official daily ZIPs.

Never modifies the original data/raw archives. Each downloaded daily ZIP is
verified against Binance's published SHA256 checksum. Missing observations
that remain after daily repair are reported and never forward-filled.
"""
from pathlib import Path
import concurrent.futures
import hashlib
import io
import json
import urllib.request
import zipfile
import pandas as pd

DATES = ['2020-01-19','2020-12-17','2021-07-01','2021-07-24','2021-07-25','2021-07-26','2021-07-27','2022-07-31','2022-10-02','2023-02-24','2024-08-12','2026-06-29']
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/raw'
TARGET=ROOT/'data/v8_verified'
DOWNLOADS=ROOT/'data/v8_verified_sources'

def fetch(date):
    filename=f'BTCUSDT-1m-{date}.zip'
    url=f'https://data.binance.vision/data/futures/um/daily/markPriceKlines/BTCUSDT/1m/{filename}'
    path=DOWNLOADS/filename
    path.parent.mkdir(parents=True,exist_ok=True)
    checksum_path=path.with_suffix('.zip.CHECKSUM')
    blob=path.read_bytes() if path.exists() else urllib.request.urlopen(url,timeout=30).read()
    checksum=checksum_path.read_text() if checksum_path.exists() else urllib.request.urlopen(url+'.CHECKSUM',timeout=30).read().decode()
    actual=hashlib.sha256(blob).hexdigest()
    if actual!=checksum.split()[0]:raise ValueError(f'checksum mismatch: {date}')
    path.write_bytes(blob);checksum_path.write_text(checksum)
    return {'date':date,'url':url,'sha256':actual,'bytes':len(blob)}

def read(path):
    with zipfile.ZipFile(path) as z:
        frame=pd.read_csv(io.BytesIO(z.read(z.namelist()[0])),header=None)
    frame=frame[pd.to_numeric(frame.iloc[:,0],errors='coerce').notna()].copy()
    frame.iloc[:,0]=pd.to_numeric(frame.iloc[:,0])
    return frame

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        provenance=list(ex.map(fetch,DATES))
    repaired_months={s[:7] for s in DATES}
    for folder in ['klines','funding','mark_price']:
        (TARGET/folder).mkdir(parents=True,exist_ok=True)
        for path in (SOURCE/folder).glob('*.zip'):
            dest=TARGET/folder/path.name
            if folder=='mark_price' and path.stem.removeprefix('BTCUSDT-1m-') in repaired_months:continue
            if not dest.exists():dest.symlink_to(path.resolve())
    coverage=[]
    for month in sorted(repaired_months):
        name=f'BTCUSDT-1m-{month}.zip'
        original=read(SOURCE/'mark_price'/name)
        frames=[original]+[read(DOWNLOADS/f'BTCUSDT-1m-{d}.zip') for d in DATES if d.startswith(month)]
        combined=pd.concat(frames).drop_duplicates(0,keep='last').sort_values(0)
        dest=TARGET/'mark_price'/name
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(name.replace('.zip','.csv'),combined.to_csv(header=False,index=False))
        start=pd.Timestamp(month+'-01',tz='UTC');end=start+pd.offsets.MonthBegin(1)
        expected=int((end-start).total_seconds()/60)
        coverage.append({'month':month,'original_rows':len(original),'repaired_rows':len(combined),'remaining_missing':expected-len(combined)})
    report={'original_data_unchanged':True,'source':'Binance official daily markPriceKlines','daily_archives':provenance,'repairs':coverage}
    for cache in (ROOT/'data').glob('v8_verified_*m.pkl'):
        cache.unlink()  # Derived bars must be rebuilt after archive repairs.
    path=ROOT/'reports/v8_research/data_repair.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':main()
