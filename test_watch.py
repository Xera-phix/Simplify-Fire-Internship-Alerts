import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import watch

SAMPLE_SRC = '''FAANG_PLUS: set[str] = {"amd", "stripe", "roblox", "meta"}\n'''


def listing(company, title, **more):
    return {"company_name": company, "company_url": "https://simplify.jobs/c/"+company,
            "title": title, "url": "https://example.com/"+company.replace(' ','-'),
            "active": True, "is_visible": True, "terms": ["Summer 2027"], **more}


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((Path(__file__).parent / 'config.json').read_text())
        self.faang = watch.fire_companies(SAMPLE_SRC)

    def test_whitelist(self):
        self.assertEqual(self.faang, {"amd", "stripe", "roblox", "meta"})
        self.assertTrue(watch.matches(listing('Stripe','Software Engineer Intern'), self.faang, self.cfg))
        self.assertFalse(watch.matches(listing('Unknown','Software Engineer Intern'), self.faang, self.cfg))
        self.assertFalse(watch.matches(listing('AMD','Software Engineer Intern'), self.faang, self.cfg))
        self.assertFalse(watch.matches(listing('Stripe','Data Analyst Intern'), self.faang, self.cfg))
        self.assertFalse(watch.matches(listing('Meta','Hardware Engineer Intern'), self.faang, self.cfg))
        self.assertTrue(watch.matches(listing('Roblox','Gameplay Software Engineer Intern'), self.faang, self.cfg))

    def test_term(self):
        job = listing('Stripe','Software Engineer Intern')
        job['terms'] = ['Winter 2027']
        self.assertFalse(watch.matches(job,self.faang,self.cfg))
        job['terms'] = ['Summer 2027']
        self.assertTrue(watch.matches(job,self.faang,self.cfg))

    def test_bootstrap_and_single_notification(self):
        jobs = [listing('Stripe','Software Engineer Intern')]
        with tempfile.TemporaryDirectory() as td, patch.object(watch,'load_url') as dl, patch.object(watch, 'create_issue') as ci:
            path=Path(td) / 'seen.json'
            dl.side_effect = [SAMPLE_SRC,json.dumps(jobs)]
            watch.run(self.cfg,path,token='dummy',repo='example/test')
            self.assertTrue(path.exists())
            self.assertEqual(ci.call_count,0)
            jobs.append(listing('Meta','Software Engineer Intern'))
            dl.side_effect = [SAMPLE_SRC,json.dumps(jobs)]
            watch.run(self.cfg,path,token='dummy',repo='example/test')
            self.assertEqual(ci.call_count,1)
            dl.side_effect = [SAMPLE_SRC,json.dumps(jobs)]
            watch.run(self.cfg,path,token='dummy',repo='example/test')
            self.assertEqual(ci.call_count,1)

if __name__ == '__main__':
    unittest.main()
