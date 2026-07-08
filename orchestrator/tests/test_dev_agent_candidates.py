import unittest

from orchestrator.dev_agent.candidates import lookup_pypi, search_crates, search_github, search_npm


class TestSearchNpm(unittest.TestCase):
    def test_parses_search_results(self):
        def fake_get(url, headers):
            self.assertIn("registry.npmjs.org/-/v1/search", url)
            return {
                "objects": [
                    {
                        "package": {
                            "name": "left-pad",
                            "description": "pad a string",
                            "license": "MIT",
                            "date": "2024-01-01T00:00:00.000Z",
                            "links": {"npm": "https://www.npmjs.com/package/left-pad"},
                        }
                    }
                ]
            }

        results = search_npm("pad", http_get=fake_get)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].ecosystem, "npm")
        self.assertEqual(results[0].name, "left-pad")
        self.assertEqual(results[0].license, "MIT")


class TestSearchCrates(unittest.TestCase):
    def test_parses_search_results_and_tolerates_missing_license(self):
        def fake_get(url, headers):
            self.assertIn("crates.io/api/v1/crates", url)
            return {
                "crates": [
                    {"name": "serde", "description": "serialization", "downloads": 999999999, "updated_at": "2026-01-01T00:00:00Z"}
                ]
            }

        results = search_crates("serialize", http_get=fake_get)

        self.assertEqual(results[0].name, "serde")
        self.assertIsNone(results[0].license)  # not present -> unknown, not guessed


class TestSearchGithub(unittest.TestCase):
    def test_parses_search_results(self):
        def fake_get(url, headers):
            self.assertIn("api.github.com/search/repositories", url)
            return {
                "items": [
                    {
                        "full_name": "psf/requests",
                        "description": "HTTP for humans",
                        "license": {"spdx_id": "Apache-2.0"},
                        "html_url": "https://github.com/psf/requests",
                        "pushed_at": "2026-01-01T00:00:00Z",
                        "stargazers_count": 50000,
                    }
                ]
            }

        results = search_github("http client", http_get=fake_get)

        self.assertEqual(results[0].name, "psf/requests")
        self.assertEqual(results[0].license, "Apache-2.0")
        self.assertEqual(results[0].popularity, 50000)

    def test_handles_null_license(self):
        def fake_get(url, headers):
            return {
                "items": [
                    {
                        "full_name": "someone/repo",
                        "description": "",
                        "license": None,
                        "html_url": "https://github.com/someone/repo",
                    }
                ]
            }

        results = search_github("x", http_get=fake_get)

        self.assertIsNone(results[0].license)


class TestLookupPypi(unittest.TestCase):
    def test_found_package(self):
        def fake_get(url, headers):
            self.assertEqual(url, "https://pypi.org/pypi/requests/json")
            return {"info": {"name": "requests", "summary": "HTTP library", "license": "Apache-2.0", "package_url": "https://pypi.org/project/requests/"}}

        result = lookup_pypi("requests", http_get=fake_get)

        self.assertEqual(result.name, "requests")
        self.assertEqual(result.ecosystem, "pypi")

    def test_not_found_returns_none(self):
        def fake_get(url, headers):
            raise Exception("404")

        result = lookup_pypi("this-package-should-not-exist-xyz", http_get=fake_get)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
