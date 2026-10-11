#!/usr/bin/env python3
"""NFL-wide per-position weekly stats and status auditor.

Uses nflverse released CSVs. No guessing, fuzzy ID joins, or filling absent stats with zero.
Python standard library only. CLI: python generate.py --season 2026
"""
import argparse
from collections import defaultdict, Counter
import csv
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TEAMS = set('ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LA LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS'.split())
TEAM_ALIASES = {'LAR':'LA', 'WSH':'WAS', 'JAC':'JAX', 'OAK':'LV', 'STL':'LA', 'SD':'LAC'}
POS_ORDER = 'QB RB FB WR TE T C G OT OG OL LT RT LG RG EDGE DE DT NT DL LB ILB OLB MLB CB S FS SS DB K P LS'.split()
POS_SUMMARY = {
 'QB': ['gp','completions','attempts','cmp_pct','passing_yards','pass_ypa','passing_tds','interceptions','carries','rushing_yards','rushing_tds'],
 'RB': ['gp','carries','rushing_yards','rush_ypa','rushing_tds','targets','receptions','receiving_yards','receiving_tds'],
 'FB': ['gp','carries','rushing_yards','rushing_tds','targets','receptions','receiving_yards','receiving_tds'],
 'WR': ['gp','targets','receptions','receiving_yards','rec_ypr','receiving_tds','carries','rushing_yards','rushing_tds'],
 'TE': ['gp','targets','receptions','receiving_yards','rec_ypr','receiving_tds'],
 'DEFAULT_OFF': ['gp','carries','rushing_yards','targets','receptions','receiving_yards'],
 'DEFAULT_DEF': ['gp','def_tackles','def_tackles_solo','def_tackles_for_loss','def_sacks','def_qb_hits','def_interceptions','def_pass_defended','def_tds'],
 'K': ['gp','fg_made','fg_att','fg_pct','pat_made','pat_att'],
 'P': ['gp','punts','punting_yards','punting_avg'],
 'LS': ['gp']
}
STAT_ALIASES = {
 'completions':['completions','passing_completions'],
 'interceptions':['passing_interceptions','interceptions'],
 'attempts':['attempts','passing_attempts'],
 'carries':['carries','rushing_attempts'],
 'fg_made':['fg_made','kicking_fgm','kicking_fg_made','field_goals_made','fgm'],
 'fg_att':['fg_att','kicking_fga','kicking_fg_att','field_goals_attempted','fga'],
 'pat_made':['pat_made','kicking_xpm','kicking_pat_made','extra_points_made'],
 'pat_att':['pat_att','kicking_xpa','kicking_pat_att','extra_points_attempted'],
 'punts':['punts','punting_punts'],
 'punting_yards':['punting_yards','punt_yards'],
}
ALL_VIEW = ['gp','completions','attempts','passing_yards','passing_tds','interceptions','carries','rushing_yards','rushing_tds','targets','receptions','receiving_yards','receiving_tds','def_tackles','def_sacks','def_interceptions']
NO_AGG = {'season','week','season_type','player_id','player_name','player_display_name','position','position_group','headshot_url','team','recent_team','opponent_team','game_id','game_type'}
NO_SUM_PATTERNS = ('_pct','_percentage','_per_','_rate','_average','_avg','_share','_epa','_wopr','_pacr','_racr','_dakota','fantasy_points')
SOURCES = lambda season: {
 'stats':f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv',
 'rosters':f'https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv',
 'injuries':f'https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv',
 'teamstats':f'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv',
}

def clean(v):
 if v is None:return ''
 s=str(v).strip()
 return '' if s.lower() in ('na','n/a','nan','null','none','<na>') else s

def team(v):
 v=clean(v).upper();return TEAM_ALIASES.get(v,v)

def fint(v):
 try:return int(float(clean(v)))
 except (TypeError,ValueError,OverflowError):return 0

def num(v):
 v=clean(v)
 if not v:return None
 try:
  f=float(v)
  return f if math.isfinite(f) else None
 except ValueError:return None

def nval(v):
 if v is None:return None
 return round(v,4) if isinstance(v,float) and abs(v-round(v))>1e-9 else int(round(v))

def read_http_csv(url, retry=3):
 last=None
 for attempt in range(retry):
  try:
   request=Request(url,headers={'User-Agent':'NFL-Stats-Verification-Tracker/1.0 (nflverse-public-csv)','Accept':'text/csv,*/*'})
   with urlopen(request,timeout=65) as response: data=response.read()
   if not data or len(data)<100:raise ValueError('empty or suspiciously short CSV')
   text=data.decode('utf-8-sig')
   rows=list(csv.DictReader(io.StringIO(text)))
   if not rows:raise ValueError('no records in CSV')
   return rows
  except (HTTPError,URLError,TimeoutError,UnicodeError,ValueError) as exc:
   last=exc
   if attempt<retry-1:time.sleep(2*(attempt+1))
 raise RuntimeError(f'Source unavailable: {url}: {last}')

def read_fixture(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def require_columns(label,rows,cols):
 if not rows:raise ValueError(label+' dataset empty')
 missing=set(cols)-set(rows[0])
 if missing:raise ValueError(label+' source schema changed; missing '+', '.join(sorted(missing)))

def in_season_reg(row,season):
 return (not clean(row.get('season')) or fint(row.get('season'))==season) and clean(row.get('season_type','REG')).upper() in ('REG','REGULAR','')

def stat_value(row,key):
 for k in STAT_ALIASES.get(key,[key]):
  if k in row:
   val=num(row[k])
   if val is not None:return val
 return None

def display_columns(pos):
 if pos in POS_SUMMARY:return POS_SUMMARY[pos]
 if pos in ('T','C','G','OT','OG','OL','LT','RT','LG','RG'):return ['gp']
 if pos in ('EDGE','DE','DT','NT','DL','LB','ILB','OLB','MLB','CB','S','FS','SS','DB'):return POS_SUMMARY['DEFAULT_DEF']
 return POS_SUMMARY['DEFAULT_OFF']

def game_status(row):
 s=clean(row.get('report_status')).lower()
 if 'questionable' in s:return 'Q'
 if 'doubtful' in s:return 'D'
 if s=='out' or s.startswith('out ') or s.startswith('out-'):return 'O'
 return ''

def roster_code(row):
 code=clean(row.get('status')).upper()
 desc=clean(row.get('status_description_abbr')).lower()
 # Generic RES is NOT assumed to mean IR.
 if 'injured reserve' in desc or re.search(r'\bir\b',desc):return 'IR'
 if code in ('PUP','SUS','EXE','RSN','RES','INA','DEV'):return code
 return ''

def safe_name(row):
 return clean(row.get('full_name')) or clean(row.get('player_display_name')) or 'Unknown player'

def build(season,stats,rosters,injuries,teamstats=None,strict=True):
 require_columns('stats',stats,['player_id','week','season_type'])
 require_columns('rosters',rosters,['gsis_id','team','position','status','week'])
 require_columns('injuries',injuries,['gsis_id','week','report_status','practice_primary_injury'])
 if strict and teamstats is None:raise ValueError('Team stats are required for aggregate reconciliation')
 if teamstats is not None:require_columns('teamstats',teamstats,['week','team','season_type'])
 warnings=[]
 stats=[r for r in stats if in_season_reg(r,season) and fint(r.get('week'))>0]
 if teamstats is not None:teamstats=[r for r in teamstats if in_season_reg(r,season) and fint(r.get('week'))>0]
 rosters=[r for r in rosters if (not clean(r.get('season')) or fint(r.get('season'))==season) and fint(r.get('week'))>0 and clean(r.get('game_type','REG')).upper() in ('REG','')]
 injuries=[r for r in injuries if in_season_reg(r,season) and fint(r.get('week'))>0]
 if not stats:raise ValueError('No regular-season stats found; publishing would falsely imply zero statistics')
 if not rosters:raise ValueError('No current regular-season rosters found')
 stat_week=max(fint(r.get('week')) for r in stats)
 roster_week=max(fint(r.get('week')) for r in rosters)
 injury_week=max((fint(r.get('week')) for r in injuries),default=0)
 if not injury_week:warnings.append('No current injury-report week found. No player is assumed healthy.')
 # Weekly roster feeds may have the next week's rosters for just a subset of teams
 # (e.g. the teams on bye). Use the latest available weekly snapshot PER TEAM.
 # Never silently treat a week-old roster as a same-week official report.
 team_roster_week={}
 for r in rosters:
  tm=team(r.get('team'))
  if tm in TEAMS:
   team_roster_week[tm]=max(team_roster_week.get(tm,0),fint(r.get('week')))
 stale={tm:wk for tm,wk in team_roster_week.items() if wk < roster_week}
 if stale:
  warnings.append('Team rosters from earlier weekly snapshots (not verified for the latest week): '+
                  ', '.join(f'{tm} W{wk}' for tm,wk in sorted(stale.items())))
 unavailable=sorted(TEAMS-set(team_roster_week))
 if unavailable:
  warnings.append('No weekly roster snapshot for teams: '+', '.join(unavailable))
 if strict and (unavailable or any(wk < roster_week-2 for wk in team_roster_week.values())):
  raise ValueError('One or more team roster snapshots are missing or more than 2 weeks old; no publish.')
 # A player may be omitted from the current roster source and still have season stats.
 released_codes={'CUT','UFA','NWT','RFA','TRC','TRD','TRT','RSR','RET'}
 current_rows=[r for r in rosters if team(r.get('team')) in TEAMS
               and fint(r.get('week'))==team_roster_week[team(r.get('team'))]
               and clean(r.get('status')).upper() not in released_codes]
 current={}
 for r in current_rows:
  pid=clean(r.get('gsis_id'))
  if not pid:continue
  prev=current.get(pid)
  if prev and team(r.get('team'))!=team(prev.get('team')):
   warnings.append(f'Conflicting latest team snapshots for player {pid}: '+
                   f'{team(prev.get("team"))} W{prev.get("week")} vs {team(r.get("team"))} W{r.get("week")}. '+
                   'Review the team assignment.')
  if (prev is None or fint(r.get('week'))>fint(prev.get('week')) or
      (fint(r.get('week'))==fint(prev.get('week')) and roster_code(prev) and not roster_code(r))):
   current[pid]=r
 roster_teams={team(r.get('team')) for r in current.values()}
 if strict and (len(roster_teams)!=32 or len(current)<1200):
  raise ValueError(f'Roster coverage below threshold after per-team fallback: {len(roster_teams)} teams, {len(current)} players. No publish.')
 if len(roster_teams)!=32:warnings.append(f'Only {len(roster_teams)} teams represented after per-team fallback; expected 32.')
 if len(current)<1200:warnings.append('Latest available team rosters contain fewer than 1,200 unique players.')
 # Include every stat-documented season participant, even if traded/released.
 agg=defaultdict(lambda:{'metrics':defaultdict(float),'fields':set(),'weeks':set(),'teams':set(),'weekly':defaultdict(lambda:defaultdict(float)),'weekly_fields':defaultdict(set)})
 # Audit player/team-week aggregate totals against separately released team box scores.
 team_player=defaultdict(lambda:defaultdict(float))
 team_fields=defaultdict(set)
 stat_schema=set(stats[0].keys())
 for r in stats:
  pid=clean(r.get('player_id'))
  if not pid:continue
  d=agg[pid];week=fint(r.get('week')); d['weeks'].add(week)
  tm=team(r.get('team') or r.get('recent_team'))
  if tm in TEAMS:d['teams'].add(tm)
  d['last_name']=clean(r.get('player_display_name') or r.get('player_name'))
  d['last_pos']=clean(r.get('position')).upper()
  d['last_team']=tm
  for k,v in r.items():
   if k in NO_AGG or k.startswith('opp_') or any(t in k for t in NO_SUM_PATTERNS):continue
   n=num(v)
   if n is not None:
    d['metrics'][k]+=n; d['fields'].add(k)
    d['weekly'][week][k]+=n;d['weekly_fields'][week].add(k)
    if tm in TEAMS:team_player[(tm,week)][k]+=n;team_fields[(tm,week)].add(k)
 # Find mismatches; report prominently rather than silently altering player totals.
 team_checks=[];tested=0
 if teamstats is not None:
  for tr in teamstats:
   tm=team(tr.get('team'));wk=fint(tr.get('week'));key=(tm,wk)
   if not tm in TEAMS:continue
   for fld in ('completions','attempts','carries','rushing_yards','passing_tds','rushing_tds','receptions'):
    official=num(tr.get(fld));actual=team_player[key].get(fld)
    if official is None or fld not in team_fields[key]:continue
    tested+=1
    if abs(official-actual)>.001:
     team_checks.append({'team':tm,'week':wk,'metric':fld,'team_feed':nval(official),'summed_players':nval(actual),'difference':nval(actual-official)})
  if strict and tested<30:raise ValueError('Insufficient team/stat consistency comparisons for publication')
  if team_checks:warnings.append(f'{len(team_checks)} player-to-team statistic discrepancies require review (see TEAM_CHECKS.csv).')
 if strict and (len(agg)<300 or len({t for a in agg.values() for t in a['teams']})<30):
  raise ValueError('Statistics player/team coverage suspiciously low; no publish')
 inj_index={}
 for r in injuries:
  if fint(r.get('week'))!=injury_week:continue
  pid=clean(r.get('gsis_id'));tm=team(r.get('team'))
  if not pid:continue
  key=(pid,tm)
  # newest official report row for this player, not arbitrary input order
  stamp=clean(r.get('date_modified'))
  if key not in inj_index or stamp>=clean(inj_index[key].get('date_modified')):inj_index[key]=r
 injury_by_id={}
 for (pid,tm0),inj in inj_index.items():
  if pid not in injury_by_id or clean(inj.get('date_modified'))>=clean(injury_by_id[pid].get('date_modified')):injury_by_id[pid]=inj
 positions=set();outputs=[];coverage=Counter()
 for pid in sorted(set(current)|set(agg)|set(injury_by_id)):
  r=current.get(pid,{});a=agg.get(pid);ix=injury_by_id.get(pid,{})
  name=safe_name(r) if r else (a['last_name'] if a else safe_name(ix))
  pos=clean(r.get('position')).upper() or (a['last_pos'] if a else clean(ix.get('position')).upper() or 'UNK')
  tm=team(r.get('team')) or (a['last_team'] if a else team(ix.get('team')))
  if tm not in TEAMS:tm='—'
  positions.add(pos)
  injury=inj_index.get((pid,tm)) if injury_week else None
  code=game_status(injury or {})
  rcode=roster_code(r)
  if not code and rcode:code=rcode
  reason=clean((injury or {}).get('report_primary_injury') or (injury or {}).get('practice_primary_injury'))
  if not code and reason and reason.lower() not in ('rest','personal','non injury related','not injury related','coach decision'):
   code='I'
  if not code:code='—'
  metrics={};available=set()
  if a:
   metrics=dict(a['metrics']);available=set(a['fields'])
  # aliases for source schemas: never introduce missing source fields as zeros
  for standard,alias_list in STAT_ALIASES.items():
   present=[k for k in alias_list if k in available]
   if present:
    metrics[standard]=metrics[present[0]];available.add(standard)
  weekly={}
  if a:
   for wk,raw in a['weekly'].items():
    wmet=dict(raw); wfields=a['weekly_fields'][wk]
    for standard,alias_list in STAT_ALIASES.items():
     matching=[k for k in alias_list if k in wfields]
     if matching:wmet[standard]=wmet[matching[0]]
    for derived,top,bottom in [('cmp_pct','completions','attempts'),('pass_ypa','passing_yards','attempts'),('rush_ypa','rushing_yards','carries'),('rec_ypr','receiving_yards','receptions'),('fg_pct','fg_made','fg_att'),('punting_avg','punting_yards','punts')]:
     if top in wmet and bottom in wmet and wmet[bottom]:wmet[derived]=round(wmet[top]/wmet[bottom]*(100 if derived in ('cmp_pct','fg_pct') else 1),1)
    wmet['gp']=1
    weekly[str(wk)]={k:nval(v) for k,v in wmet.items()}
  # GP here means stat-recorded week appearances, not official games participated for OL etc.
  gp=len(a['weeks']) if a else None
  if a:metrics['gp']=gp;available.add('gp')
  for key,numkey,denkey in [('cmp_pct','completions','attempts'),('pass_ypa','passing_yards','attempts'),('rush_ypa','rushing_yards','carries'),('rec_ypr','receiving_yards','receptions'),('fg_pct','fg_made','fg_att'),('punting_avg','punting_yards','punts')]:
   if numkey in available and denkey in available and metrics[denkey]:
    metrics[key]=round(metrics[numkey]/metrics[denkey]*(100 if key in ('cmp_pct','fg_pct') else 1),1)
  note=[]
  if not r:note.append('Not on latest weekly roster; sourced from '+('statistical participation' if a else 'injury report'))
  if not a:note.append('No statistical row; does not prove no game participation')
  if r and fint(r.get('week'))<roster_week:note.append(f'Team roster snapshot is week {r.get("week")}, not league latest week {roster_week}; verify changes')
  if injury_week and injury_week < roster_week:note.append('Injury data is older than roster data')
  if tm=='—':note.append('Unresolved NFL team')
  row={'id':pid,'name':name,'team':tm,'pos':pos,'jersey':clean(r.get('jersey_number')),
       'roster':clean(r.get('status')) or 'NOT IN CURRENT ROSTER','status':code,
       'injury_reason':reason,'practice_status':clean((injury or {}).get('practice_status')),
       'game_status_text':clean((injury or {}).get('report_status')),
       'stats_weeks':sorted(a['weeks']) if a else [],'stats_teams':sorted(a['teams']) if a else [],
       'stats_week':stat_week,'roster_week':fint(r.get('week')) if r else None,'injury_week':injury_week if injury else None,
       'has_stats':bool(a),'stat_fields':sorted(available),'metrics':{k:nval(v) for k,v in metrics.items()},
       'notes':'; '.join(note),'weekly':weekly}
  outputs.append(row)
  coverage['rostered']+=bool(r);coverage['stats_participants']+=bool(a);coverage['with_injury_notice']+=bool(injury)
  if note:coverage['with_notes']+=1
 if stat_week>roster_week:warnings.append('Stats are newer than latest-week roster: team assignments may have changed.')
 if injury_week and injury_week < stat_week:warnings.append('Injury report week precedes most recent stats week; designations may be outdated.')
 data={'season':season,'retrieved_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'stats_week':stat_week,'roster_week':roster_week,'injury_week':injury_week,
       'team_count':len(roster_teams),'roster_team_weeks':dict(sorted(team_roster_week.items())),'players':len(outputs),'positions':sorted(positions),
       'counts':dict(coverage),'warnings':warnings,'sources':SOURCES(season),'rows':outputs,'team_checks':team_checks,'team_comparisons':tested,
       'method':'Player ID / GSIS join; latest available snapshot per team, with snapshot week disclosed; all season participants; REG stats only; additive metrics aggregated. ' +
       'GP counts recorded statistical weeks, not official games played. Injury codes reflect only newest available report week. Absent stats are null.'}
 return data

def spreadsheet_cell(value):
 if value is None:return ''
 if isinstance(value,(int,float)):return value
 if isinstance(value,list):value=', '.join(map(str,value))
 v=str(value)
 # Prevent spreadsheet injection if this text ever comes from a remote player record
 return "'"+v if v.startswith(('=','+','-','@','\t','\r')) else v

def flatten(row,cols):
 base={'Player':row['name'],'Player ID':row['id'],'Team':row['team'],'Position':row['pos'],'Jersey':row['jersey'],
       'Status':row['status'],'Roster designation':row['roster'],'Injury':row['injury_reason'],
       'Practice':row['practice_status'],'Official game designation':row['game_status_text'],
       'Injury report week':row['injury_week'],'Stat source week':row['stats_week'],'Stats team(s)':row['stats_teams'],
       'Notes':row['notes']}
 out=list(base.values())
 for c in cols:out.append(row['metrics'].get(c))
 return out

def output_files(data,root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 root.joinpath('data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 basecols=['Player','Player ID','Team','Position','Jersey','Status','Roster designation','Injury','Practice','Official game designation','Injury report week','Stat source week','Stats team(s)','Notes']
 def write_csv(path,rows,columns):
  with open(path,'w',newline='',encoding='utf-8-sig') as f:
   w=csv.writer(f);w.writerow(basecols+[c.replace('_',' ').title() for c in columns]);
   for r in rows:w.writerow([spreadsheet_cell(c) for c in flatten(r,columns)])
 positions=sorted({r['pos'] for r in data['rows']},key=lambda p:(POS_ORDER.index(p) if p in POS_ORDER else 999,p))
 write_csv(root/'ALL_PLAYERS.csv',data['rows'],ALL_VIEW)
 for p in positions:
  write_csv(root/(p.replace('/','_')+'.csv'),[r for r in data['rows'] if r['pos']==p],display_columns(p))
 # All data provider fields available for analysis, explicitly preserving missing as blank
 metric_fields=sorted({k for r in data['rows'] for k in r['stat_fields'] if k not in ('gp',)})
 write_csv(root/'ALL_METRICS.csv',data['rows'],['gp']+metric_fields)
 q=[]
 for r in data['rows']:
  if r['notes']:q.append([r['id'],r['name'],r['team'],r['pos'],r['notes']])
 with open(root/'TEAM_CHECKS.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['Team','Week','Metric','Team box-score feed','Summed player feed','Difference'])
  for c in data['team_checks']:w.writerow([c['team'],c['week'],c['metric'],c['team_feed'],c['summed_players'],c['difference']])
 with open(root/'REVIEW_FLAGS.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['GSIS ID','Player','Team','Position','Review note']);w.writerows(q)
 report={k:v for k,v in data.items() if k!='rows'}
 report['pos_counts']=dict(Counter(r['pos'] for r in data['rows']))
 (root/'VALIDATION_REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 template=Path(__file__).with_name('template.html').read_text(encoding='utf-8')
 root.joinpath('index.html').write_text(template.replace('/*DATA_JSON*/',json.dumps(data,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')


def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--season',type=int,default=2026)
 ap.add_argument('--out',default='site')
 ap.add_argument('--fixtures',help='Test-only folder of stats.csv, rosters.csv, injuries.csv (no internet required)')
 ap.add_argument('--allow-small-fixture',action='store_true',help='Test only; relax 32-team threshold')
 args=ap.parse_args();sources=SOURCES(args.season)
 inputs={}
 for name,url in sources.items():
  print(f'Fetching {name}: {url}',flush=True)
  try: inputs[name]=read_fixture(Path(args.fixtures)/(name+'.csv')) if args.fixtures else read_http_csv(url)
  except Exception as e:raise SystemExit(f'FAILED: {e}') from e
  print(f'  {len(inputs[name]):,} rows',flush=True)
 try:data=build(args.season,inputs['stats'],inputs['rosters'],inputs['injuries'],inputs['teamstats'],strict=not args.allow_small_fixture)
 except ValueError as e:raise SystemExit(f'VALIDATION FAILED: {e}') from e
 output_files(data,args.out)
 print('SUCCESS: season',args.season,'players',data['players'],'teams',data['team_count'],'stat week',data['stats_week'],'injury week',data['injury_week'])
 if data['warnings']:print('WARNINGS:',*data['warnings'],sep='\n - ')

if __name__=='__main__':main()
