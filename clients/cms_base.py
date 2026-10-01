"""What the pipeline needs from the Yellow Slate CMS. The fake and the real API client both follow this."""

import config


class CMSError(RuntimeError):
    pass


class CMS:
    def search_school(self, name, city, area):
        """Return {"id", "name", "slug"} for an existing school in this city + area, or None."""
        raise NotImplementedError

    def create_school(self, name, city, area, email):
        """Create with verified = No, claimed = No. Return {"id", "name", "slug"}."""
        raise NotImplementedError


def profile_url(slug):
    return f"{config.SITE}/school/{slug}"


def get_cms():
    if config.CMS_MODE == "api":
        from clients.cms_api import ApiCMS
        return ApiCMS()
    from clients.cms_fake import FakeCMS
    return FakeCMS()
