"""Bootstrap only the 18 newly enabled funds after all sources validate."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from active_candidate_adapter import ENABLED_ETFS, fetch_candidate


def validate_all():
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames=dict(zip(ENABLED_ETFS,pool.map(fetch_candidate,ENABLED_ETFS)))
    for ticker,df in frames.items():
        assert not df.empty and df['ticker'].is_unique
        assert df['date'].nunique()==1 and set(df['etf'])=={ticker}
        assert df['shares'].notna().all()
    return frames


def main():
    frames=validate_all()  # No writes unless every new source passes first.
    import fetch_holdings as etl
    from equity_expansion_adapter import APPROVED_ETFS
    assert not set(ENABLED_ETFS).intersection(APPROVED_ETFS)
    assert not set(ENABLED_ETFS).intersection(etl.ADDITIONAL_ETFS)
    assert urlparse(etl.SUPABASE_URL).hostname=='nzpshofcmjadxgbbsczy.supabase.co'
    report=[]
    out=Path('artifacts/enabled-active-etfs')
    out.mkdir(parents=True,exist_ok=True)
    for ticker,df in frames.items():
        status=etl.save_etf(ticker,df)
        assert status in {'saved','unchanged'},(ticker,status)
        stored=etl._load_snapshot(ticker,str(df.iloc[0]['date']))
        expected={r['ticker']:{'weight':float(r['weight']),'shares':float(r['shares'])} for r in df.to_dict('records')}
        assert etl._same_snapshot(stored,expected),ticker+' persisted snapshot differs'
        # A retry must neither duplicate holdings nor emit first-snapshot signals.
        assert etl.save_etf(ticker,df)=='unchanged'
        report.append({'etf':ticker,'date':str(df.iloc[0]['date']),'rows':len(df),'status':status})
        df.to_json(out/(ticker+'.json'),orient='records',indent=2)
        print('DATABASE_VERIFIED',json.dumps(report[-1]),flush=True)
    (out/'report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
