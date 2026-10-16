"""What the pipeline needs from the Yellow Slate blog API. The real client follows this.

Mirrors clients/cms_base.py. BLOG_MODE=off (the default) means publishing stays manual:
the blog is reviewed in blog.docx and pasted into the CMS by hand.
"""

import config


class BlogError(RuntimeError):
    pass


class Blog:
    def create_draft(self, blog):
        """blog: {"title", "meta_title", "meta_description", "slug", "city", "area", "content"}.

        Creates an UNPUBLISHED draft. Returns {"id", "slug", "status", "edit_url"}.

        Idempotent on slug, in the narrow sense that a slug that already exists returns the
        existing post and never a second one. It is not an update: measured Oct 16 2026,
        the content sent with a repeat call is discarded. "created": False in the reply
        therefore means "your body went nowhere", which stages/draft.py treats as a failure.
        """
        raise NotImplementedError

    def upload_image(self, path, alt=""):
        """Upload one local .jpg or .png. Returns {"url"} as an absolute URL usable in the body."""
        raise NotImplementedError


def get_blog():
    if config.BLOG_MODE == "api":
        from clients.blog_api import ApiBlog
        return ApiBlog()
    raise BlogError("BLOG_MODE is not 'api'. Publishing is manual: review blog.docx and paste it in.")
