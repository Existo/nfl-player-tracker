import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from generate import build,output_files,display_columns,SOURCES,game_status,roster_code,spreadsheet_cell

class NflDataTests(unittest.TestCase):
 def setUp(self):
  self.rosters=[{'season':'2026','week':'5','game_type':'REG','gsis_id':'00-111','full_name':'Example Quarterback','team':'PHI','position':'QB','status':'ACT','jersey_number':'1'},
                {'season':'2026','week':'5','game_type':'REG','gsis_id':'00-222','full_name':'Example Receiver','team':'PHI','position':'WR','status':'ACT'},
                {'season':'2026','week':'5','game_type':'REG','gsis_id':'00-333','full_name':'Example Lineman','team':'DAL','position':'G','status':'ACT'},
                {'season':'2026','week':'5','game_type':'REG','gsis_id':'00-444','full_name':'Example Reserve','team':'PHI','position':'CB','status':'RES'}]
  self.stats=[{'season':'2026','week':'1','season_type':'REG','player_id':'00-111','player_display_name':'Example Quarterback','team':'PHI','position':'QB','completions':'20','attempts':'30','passing_yards':'250','passing_tds':'2','passing_interceptions':'1','carries':'2','rushing_yards':'12'},
              {'season':'2026','week':'2','season_type':'REG','player_id':'00-111','player_display_name':'Example Quarterback','team':'PHI','position':'QB','completions':'10','attempts':'20','passing_yards':'100','passing_tds':'1','passing_interceptions':'0'},
              {'season':'2026','week':'2','season_type':'REG','player_id':'00-222','player_display_name':'Example Receiver','team':'PHI','position':'WR','receptions':'3','receiving_yards':'55','targets':'5'},
              {'season':'2026','week':'2','season_type':'REG','player_id':'00-555','player_display_name':'Former Running Back','team':'DAL','position':'RB','carries':'3','rushing_yards':'11'}]
  self.injuries=[{'season':'2026','week':'5','season_type':'REG','gsis_id':'00-222','team':'PHI','report_status':'Questionable','practice_primary_injury':'Knee','date_modified':'2026-10-09'},
                 {'season':'2026','week':'5','season_type':'REG','gsis_id':'00-111','team':'PHI','report_status':'','practice_primary_injury':'Ankle','date_modified':'2026-10-09'},
                 {'season':'2026','week':'5','season_type':'REG','gsis_id':'00-444','team':'PHI','report_status':'','practice_primary_injury':'','date_modified':'2026-10-09'}]
  self.teamstats=[{'season':'2026','week':'1','season_type':'REG','team':'PHI','completions':'20','attempts':'30','passing_tds':'2'},
                  {'season':'2026','week':'2','season_type':'REG','team':'PHI','completions':'10','attempts':'20','passing_tds':'1','receptions':'3'},
                  {'season':'2026','week':'2','season_type':'REG','team':'DAL','carries':'4'}]
 def test_season_sums_week_and_status(self):
  d=build(2026,self.stats,self.rosters,self.injuries,self.teamstats,strict=False)
  byid={r['id']:r for r in d['rows']};qb=byid['00-111'];wr=byid['00-222']
  self.assertEqual(qb['metrics']['completions'],30)
  self.assertEqual(qb['metrics']['attempts'],50)
  self.assertEqual(qb['metrics']['cmp_pct'],60)
  self.assertEqual(qb['metrics']['interceptions'],1)
  self.assertEqual(qb['metrics']['gp'],2)
  self.assertEqual(qb['weekly']['1']['passing_yards'],250)
  self.assertEqual(qb['weekly']['2']['passing_yards'],100)
  self.assertEqual(qb['status'],'I')
  self.assertEqual(wr['status'],'Q')
  self.assertEqual(byid['00-444']['status'],'RES') # Never mislabel generic reserve as injured reserve
  self.assertNotIn('gp',byid['00-333']['metrics']) # A lineman with no stat row is NOT zero games played
  self.assertEqual(byid['00-555']['roster'],'NOT IN CURRENT ROSTER')
  self.assertEqual(d['team_checks'][0]['metric'],'carries')
  self.assertTrue('5' in str(d['injury_week']))
 def test_reject_bad_schemas(self):
  with self.assertRaisesRegex(ValueError,'schema changed'):
   build(2026,self.stats,self.rosters,[{'bogus':'bad'}],self.teamstats,strict=False)
 def test_strict_rejects_partial_teams(self):
  with self.assertRaisesRegex(ValueError,'below threshold'):
   build(2026,self.stats,self.rosters,self.injuries,self.teamstats,strict=True)
 def test_status_and_csv_injection(self):
  self.assertEqual(game_status({'report_status':'Doubtful'}),'D')
  self.assertEqual(game_status({'report_status':'Out'}),'O')
  self.assertEqual(roster_code({'status':'RES'}),'RES')
  self.assertEqual(roster_code({'status':'RES','status_description_abbr':'Injured Reserve'}),'IR')
  self.assertEqual(spreadsheet_cell('=1+1'),"'=1+1")
 def test_artifact_generation(self):
  d=build(2026,self.stats,self.rosters,self.injuries,self.teamstats,strict=False)
  with tempfile.TemporaryDirectory() as p:
   output_files(d,p)
   for f in ('index.html','data.json','ALL_PLAYERS.csv','ALL_METRICS.csv','QB.csv','G.csv','REVIEW_FLAGS.csv','TEAM_CHECKS.csv','VALIDATION_REPORT.json'):
    self.assertTrue(Path(p,f).exists(),f)
   html=Path(p,'index.html').read_text()
   self.assertIn('Example Quarterback',html)
   self.assertNotIn('/*DATA_JSON*/',html)
   with Path(p,'ALL_PLAYERS.csv').open(encoding='utf-8-sig',newline='') as f:
    rr=list(csv.reader(f))
    self.assertEqual(len(rr),len(d['rows'])+1)

if __name__=='__main__':unittest.main()
