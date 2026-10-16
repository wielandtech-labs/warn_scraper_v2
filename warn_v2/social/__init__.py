"""Outbound social alerts: large new WARN notices to Bluesky and chat webhooks.

Driven by ``warn-v2 post-alerts`` (see ``warn_v2.social.run``). Each notice is
posted at most once per platform, tracked in ``notice_social_posts``.
"""
