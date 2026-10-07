"""Outlook: statistically tested, forward-looking claims about WARN layoffs.

Computed once a week by the sentiment-report CronJob (see build.build_outlook)
and written to outlook.json, which /api/outlook serves verbatim — like
forecast.py, nothing here runs in the API request path. numpy/statsmodels are
imported lazily inside the fitting functions so importing this package stays
cheap.

Every published claim must clear a statistical gate (multiple-testing-corrected
q-value or confidence interval); claims that don't clear it are not emitted.
"""
