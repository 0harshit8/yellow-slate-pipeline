"""Real Yellow Slate CMS client. Filled in once their tech team shares the API docs.

Until then CMS_MODE=fake. Switching to CMS_MODE=api before this is written fails loudly
instead of silently doing nothing.
"""

from clients.cms_base import CMS, CMSError


class ApiCMS(CMS):
    def __init__(self):
        raise CMSError("Real CMS API client not written yet. Waiting on Yellow Slate docs. Use CMS_MODE=fake.")
