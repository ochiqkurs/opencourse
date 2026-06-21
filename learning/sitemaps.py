"""XML sitemaps for search-engine discovery. Wired into config/urls.py at
/sitemap.xml. The domain comes from the request host (django.contrib.sites is
not installed; get_current_site falls back to a RequestSite), so production
serves https://ochiqkurs.uz/... URLs automatically."""
from django.contrib.auth import get_user_model
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Course, LearningPath

User = get_user_model()


class StaticViewSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'daily'
    priority = 0.6

    def items(self):
        return ['home', 'learning:course_list', 'learning:learning_path_list',
                'learning:leaderboard']

    def location(self, name):
        return reverse(name)


class CourseSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Course.objects.filter(status='published')

    def lastmod(self, obj):
        return obj.published_at


class CategorySitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        return Category.objects.all()


class LearningPathSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return LearningPath.objects.all()


class InstructorSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        # Only users who actually teach a published course have a public
        # instructor page (external YouTube creators have a NULL instructor FK).
        return (
            User.objects
            .filter(taught_courses__status='published')
            .distinct()
            .order_by('username')
        )

    def location(self, obj):
        return reverse('learning:instructor_detail', args=[obj.username])


SITEMAPS = {
    'static': StaticViewSitemap,
    'courses': CourseSitemap,
    'categories': CategorySitemap,
    'paths': LearningPathSitemap,
    'instructors': InstructorSitemap,
}
