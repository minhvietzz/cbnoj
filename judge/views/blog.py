from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Count, FilteredRelation, Q
from django.db.models.expressions import F, Value
from django.db.models.functions import Coalesce
from django.http import (Http404, HttpResponse, HttpResponseBadRequest,
                         HttpResponseForbidden, HttpResponseNotFound,
                         HttpResponseRedirect)
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import CreateView, ListView, UpdateView
from django.views.generic.detail import SingleObjectMixin, View
from reversion import revisions

from judge.comments import CommentedDetailView
from judge.dblock import LockModel
from judge.forms import BlogPostForm
from judge.models import (BlogPost, BlogPostTag, BlogVote, Comment, Contest, Language,
                          Problem, Profile, Submission, Ticket)
from judge.tasks.webhook import on_new_blogpost
from judge.utils.cachedict import CacheDict
from judge.utils.diggpaginator import DiggPaginator
from judge.utils.opengraph import generate_opengraph
from judge.utils.tickets import filter_visible_tickets
from judge.utils.unicode import remove_accents
from judge.utils.views import TitleMixin, generic_message


@login_required
def vote_blog(request, delta):
    if abs(delta) != 1:
        return HttpResponseBadRequest(_('Messing around, are we?'), content_type='text/plain')

    if request.method != 'POST':
        return HttpResponseForbidden()

    if 'id' not in request.POST or len(request.POST['id']) > 10:
        return HttpResponseBadRequest()

    if request.profile.is_new_user:
        return HttpResponseBadRequest(_('You must solve at least %d problems before you can vote.')
                                      % settings.VNOJ_INTERACT_MIN_PROBLEM_COUNT,
                                      content_type='text/plain')

    if request.profile.mute:
        suffix_msg = '' if request.profile.ban_reason is None else _(' Reason: ') + request.profile.ban_reason
        return HttpResponseBadRequest(_('Your part is silent, little toad.') + suffix_msg, content_type='text/plain')

    try:
        blog_id = int(request.POST['id'])
    except ValueError:
        return HttpResponseBadRequest()

    try:
        blog = BlogPost.objects.filter(id=blog_id).get()
    except BlogPost.DoesNotExist:
        return HttpResponseNotFound(_('Blog post not found.'), content_type='text/plain')

    if blog.authors.filter(id=request.profile.id).exists():
        return HttpResponseBadRequest(_('You cannot vote your own blog'), content_type='text/plain')

    vote = BlogVote()
    vote.blog_id = blog_id
    vote.voter = request.profile
    vote.score = delta

    while True:
        try:
            vote.save()
        except IntegrityError:
            with LockModel(write=(BlogVote,)):
                try:
                    vote = BlogVote.objects.get(blog_id=blog_id, voter=request.profile)
                except BlogVote.DoesNotExist:
                    # We must continue racing in case this is exploited to manipulate votes.
                    continue
                return HttpResponseBadRequest(_('You cannot vote twice.'), content_type='text/plain')
        else:
            BlogPost.objects.get(id=blog_id).vote(delta)
        break
    return HttpResponse('success', content_type='text/plain')


def upvote_blog(request):
    return vote_blog(request, 1)


def downvote_blog(request):
    return vote_blog(request, -1)


class BlogPostMixin(object):
    model = BlogPost
    pk_url_kwarg = 'id'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        post = super(BlogPostMixin, self).get_object(queryset)
        if not post.is_editable_by(self.request.user):
            raise PermissionDenied()
        return post


class PostListBase(ListView):
    model = BlogPost
    paginate_by = 10
    context_object_name = 'posts'
    title = None

    def get_paginator(self, queryset, per_page, orphans=0,
                      allow_empty_first_page=True, **kwargs):
        return DiggPaginator(queryset, per_page, body=6, padding=2,
                             orphans=orphans, allow_empty_first_page=allow_empty_first_page, **kwargs)

    def ignore_magazine_tag(self, queryset):
        if settings.VNOJ_MAGAZINE_TAG_SLUG:
            queryset = queryset.exclude(tags__slug=settings.VNOJ_MAGAZINE_TAG_SLUG)
        return queryset

    def get_queryset(self):
        queryset = (BlogPost.objects.filter(visible=True, publish_on__lte=timezone.now())
                    .prefetch_related('authors__user', 'authors__display_badge'))
        queryset = self.ignore_magazine_tag(queryset)
        if self.request.user.is_authenticated:
            profile = self.request.profile
            queryset = queryset.annotate(
                my_vote=FilteredRelation('votes', condition=Q(votes__voter_id=profile.id)),
            ).annotate(vote_score=Coalesce(F('my_vote__score'), Value(0)))
        return queryset

    def get_context_data(self, **kwargs):
        context = super(PostListBase, self).get_context_data(**kwargs)
        context['first_page_href'] = None
        context['title'] = self.title or _('Page %d of Posts') % context['page_obj'].number
        context['post_comment_counts'] = {
            int(page[2:]): count for page, count in
            Comment.objects
                   .filter(page__in=['b:%d' % post.id for post in context['posts']], hidden=False)
                   .values_list('page').annotate(count=Count('page')).order_by()
        }
        return context


class ModernBlogList(PostListBase):
    template_name = 'blog/modern-list.html'
    title = _('Blog')

    def ignore_magazine_tag(self, queryset):
        # we do not ignore magazine tag here
        return queryset

    def get_queryset(self):
        queryset = super(ModernBlogList, self).get_queryset()
        queryset = queryset.prefetch_related('tags').filter(global_post=True)

        # Search functionality
        search_query = self.request.GET.get('q', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(content__icontains=search_query) |
                Q(summary__icontains=search_query),
            )

        # Tag filter
        tag_slug = self.request.GET.get('tag', '').strip()
        if not tag_slug and settings.VNOJ_MAGAZINE_TAG_SLUG:
            tag_slug = settings.VNOJ_MAGAZINE_TAG_SLUG
        queryset = queryset.filter(tags__slug=tag_slug)

        # Sort functionality
        sort_by = self.request.GET.get('sort', 'latest').strip()
        if sort_by == 'top':
            queryset = queryset.order_by('-score', '-publish_on')
        else:
            queryset = queryset.order_by('-sticky', '-publish_on')

        return queryset

    def get_context_data(self, **kwargs):
        context = super(ModernBlogList, self).get_context_data(**kwargs)
        context['page_prefix'] = reverse('blog_modern_list')

        # Pass current filters to template
        context['current_search'] = self.request.GET.get('q', '')
        context['current_filter'] = self.request.GET.get('filter', '')
        context['current_sort'] = self.request.GET.get('sort', 'latest')
        context['current_tag'] = self.request.GET.get('tag', '')

        if settings.VNOJ_MAGAZINE_TAG_SLUG:
            context['tags'] = BlogPostTag.objects.exclude(slug=settings.VNOJ_MAGAZINE_TAG_SLUG)
        else:
            context['tags'] = []
        return context


class PostList(PostListBase):
    template_name = 'blog/list.html'
    show_all_blogs = False
    tab = 'home'

    def get_queryset(self):
        queryset = super(PostList, self).get_queryset()

        queryset = queryset.filter(organization=None)

        if 'show_all_blogs' in self.request.GET:
            self.show_all_blogs = self.request.session['show_all_blogs'] = self.request.GET['show_all_blogs'] == 'true'
        else:
            self.show_all_blogs = self.request.session.get('show_all_blogs', False)

        if self.show_all_blogs:
            self.tab = 'blog_list'
            queryset = queryset.order_by('-publish_on')
        else:
            queryset = queryset.filter(global_post=True).order_by('-sticky', '-publish_on')

        return queryset

    def get_context_data(self, **kwargs):
        context = super(PostList, self).get_context_data(**kwargs)
        context['first_page_href'] = reverse('home')

        context['newsfeed_link'] = f"{reverse('home')}?show_all_blogs=false"
        context['all_blogs_link'] = f"{reverse('home')}?show_all_blogs=true"

        context['show_all_blogs'] = self.show_all_blogs
        context['gcse_url'] = settings.GOOGLE_SEARCH_ENGINE_URL

        context['page_prefix'] = reverse('blog_post_list')
        context['comments'] = Comment.most_recent(self.request.user, 10)
        context['new_problems'] = Problem.get_public_problems() \
                                         .order_by('-date', '-id')[:settings.DMOJ_BLOG_NEW_PROBLEM_COUNT]
        context['page_titles'] = CacheDict(lambda page: Comment.get_page_title(page))

        context['user_count'] = Profile.objects.filter(user__is_active=True).count
        context['problem_count'] = Problem.get_public_problems().count
        context['submission_count'] = Submission.objects.count
        context['language_count'] = Language.objects.filter(judges__isnull=False).distinct().count

        now = timezone.now()

        visible_contests = Contest.get_visible_contests(self.request.user).filter(is_visible=True) \
                                  .order_by('start_time')

        context['current_contests'] = visible_contests.filter(start_time__lte=now, end_time__gt=now)
        context['future_contests'] = visible_contests.filter(start_time__gt=now)

        context['top_rated_users'] = self.get_top_rated_users()
        context['top_contrib'] = self.get_top_contributors()

        if self.request.user.is_authenticated:
            context['own_open_tickets'] = (
                Ticket.objects.filter(user=self.request.profile, is_open=True).order_by('-id')
                              .prefetch_related('linked_item').select_related('user__user', 'user__display_badge')
            )
        else:
            context['own_open_tickets'] = []

        # Superusers better be staffs, not the spell-casting kind either.
        if self.request.user.is_staff:
            tickets = (Ticket.objects.order_by('-id').filter(is_open=True).prefetch_related('linked_item')
                             .select_related('user__user', 'user__display_badge'))
            context['open_tickets'] = filter_visible_tickets(tickets, self.request.user)[:10]
        else:
            context['open_tickets'] = []

        context['tab'] = self.tab
        context['left_align_tabs'] = True

        if self.template_name == 'home.html':
            context.update(self.get_dashboard_context(context))

        return context

    def get_dashboard_context(self, context):
        # Data for the dashboard-style home page. Everything here is small and cached or cheap.
        from datetime import timedelta

        from django.core.cache import cache
        from django.db.models.functions import TruncDate

        from judge.models import Course, CourseLesson, CourseRole
        from judge.views.course import lesson_progress

        user = self.request.user
        profile = self.request.profile if user.is_authenticated else None
        data = {}

        featured = None
        for group in (context['current_contests'], context['future_contests']):
            featured = next(iter(group), None)
            if featured:
                data['home_featured_state'] = 'live' if group is context['current_contests'] else 'upcoming'
                break
        data['home_featured_contest'] = featured

        if profile is not None:
            data['home_rank'] = Profile.objects.filter(
                is_unlisted=False, performance_points__gt=profile.performance_points,
            ).count() + 1
            data['home_points'] = profile.performance_points
            data['home_solved'] = profile.problem_count

        data['home_dashboard'] = True
        if profile is not None:
            from judge.utils.streak import streak_info
            streak = streak_info(profile)
            today = timezone.localdate()
            goal = getattr(settings, 'VNOJ_DAILY_GOAL', 3)
            done = (Submission.objects.filter(user=profile, result='AC', date__date=today)
                    .values('problem_id').distinct().count())
            data.update({
                'home_streak': streak['current'],
                'home_streak_today': streak['today'],
                'home_goal': goal,
                'home_goal_done': min(done, goal),
                'home_goal_left': max(goal - done, 0),
                'home_goal_pct': int(round(100.0 * min(done, goal) / goal)) if goal else 100,
            })

        data['home_top_users'] = list(
            Profile.objects.filter(is_unlisted=False).order_by('-performance_points', '-problem_count')
                   .select_related('user')[:5],
        )

        course = None
        if profile is not None:
            role = (CourseRole.objects.filter(user=profile).select_related('course')
                    .order_by('-id').first())
            course = role.course if role else None
        if course is None:
            course = (Course.objects.filter(is_public=True, is_open=True)
                            .annotate(n_lessons=Count('lessons', filter=Q(lessons__is_visible=True)))
                            .order_by('-n_lessons', '-created').first())
        if course is not None:
            lessons = list(CourseLesson.objects.filter(course=course, is_visible=True).order_by('order', 'id')
                           .prefetch_related('lesson_problems__problem')[:12])
            progress = lesson_progress(profile, lessons) if profile is not None else {}
            data['home_course'] = course
            data['home_lessons'] = [{
                'lesson': lesson,
                'percent': progress.get(lesson.id, {}).get('percent'),
                'solved': progress.get(lesson.id, {}).get('solved'),
                'total': progress.get(lesson.id, {}).get('total'),
            } for lesson in lessons]

        def week_activity():
            today = timezone.localdate()
            start = today - timedelta(days=6)
            rows = (Submission.objects.filter(date__date__gte=start)
                    .annotate(day=TruncDate('date'))
                    .values('day').annotate(total=Count('id'), ok=Count('id', filter=Q(result='AC')))
                    .order_by('day'))
            by_day = {r['day']: r for r in rows}
            out = []
            for i in range(7):
                day = start + timedelta(days=i)
                r = by_day.get(day, {'total': 0, 'ok': 0})
                out.append({'day': day, 'ok': r['ok'], 'bad': r['total'] - r['ok']})
            peak = max([d['ok'] + d['bad'] for d in out] + [1])
            for d in out:
                d['ok_h'] = int(round(130.0 * d['ok'] / peak))
                d['bad_h'] = int(round(130.0 * d['bad'] / peak))
            return out

        data['home_activity'] = cache.get_or_set('home_week_activity', week_activity, 300)
        return data

    def get_top_rated_users(self):
        return (Profile.objects.filter(rating__isnull=False, is_unlisted=False)
                .order_by('-rating')
                .only('user', 'rating', 'display_rank', 'display_badge', 'username_display_override')
                .select_related('user', 'display_badge')
                [:settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT])

    def get_top_contributors(self):
        return (Profile.objects.order_by('-contribution_points')
                .filter(contribution_points__gt=0, is_unlisted=False)
                .only('user', 'contribution_points', 'display_rank', 'display_badge', 'rating',
                      'username_display_override')
                .select_related('user', 'display_badge')
                [:settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT])


class PostView(TitleMixin, CommentedDetailView):
    model = BlogPost
    pk_url_kwarg = 'id'
    context_object_name = 'post'
    template_name = 'blog/content.html'

    def get_title(self):
        return self.object.title

    def get_comment_page(self):
        return 'b:%s' % self.object.id

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_authenticated:
            profile = self.request.profile
            queryset = queryset.annotate(
                my_vote=FilteredRelation('votes', condition=Q(votes__voter_id=profile.id)),
            ).annotate(vote_score=Coalesce(F('my_vote__score'), Value(0)))
        return queryset

    def get_context_data(self, **kwargs):
        context = super(PostView, self).get_context_data(**kwargs)

        metadata = generate_opengraph('generated-meta-blog:%d' % self.object.id,
                                      self.object.summary or self.object.content, 'blog')
        context['meta_description'] = metadata[0]
        context['og_image'] = self.object.og_image or metadata[1]

        return context

    def get_object(self, queryset=None):
        post = super(PostView, self).get_object(queryset)
        if not post.can_see(self.request.user):
            raise Http404()
        return post


class PostModernView(PostView):
    template_name = 'blog/modern-content.html'


class PostComments(CommentedDetailView):
    model = BlogPost
    pk_url_kwarg = 'id'
    context_object_name = 'post'
    template_name = 'blog/comments-tab.html'
    skip_comment_list = False

    def get_comment_page(self):
        return 'b:%s' % self.object.id

    def get_object(self, queryset=None):
        post = super(PostComments, self).get_object(queryset)
        if not post.can_see(self.request.user):
            raise Http404()
        return post


class BlogPostCreate(TitleMixin, CreateView):
    template_name = 'blog/edit.html'
    model = BlogPost
    form_class = BlogPostForm
    context_object_name = 'post'

    def get_title(self):
        return _('Creating new blog post')

    def get_content_title(self):
        return _('Creating new blog post')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        with revisions.create_revision(atomic=True):
            post = form.save()
            post.slug = remove_accents(self.request.user.username.lower())
            post.publish_on = timezone.now()
            if not form.cleaned_data.get('authors'):
                post.authors.add(self.request.user.profile)
            else:
                post.authors.set(form.cleaned_data['authors'])
            post.save()

            revisions.set_comment(_('Created on site'))
            revisions.set_user(self.request.user)

        on_new_blogpost(post.id)

        return HttpResponseRedirect(post.get_absolute_url())

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied()

        # Check if user has permission to create blog posts
        if request.official_contest_mode or request.user.profile.problem_count < settings.VNOJ_BLOG_MIN_PROBLEM_COUNT \
                and not request.user.is_superuser and not hasattr(self, 'organization'):
            return generic_message(request, _('Permission denied'),
                                   _('You cannot create blog post.\n'
                                     'Note: You need to solve at least %d problems to create new blog post.')
                                   % settings.VNOJ_BLOG_MIN_PROBLEM_COUNT)

        return super().dispatch(request, *args, **kwargs)


class BlogPostEdit(BlogPostMixin, TitleMixin, UpdateView):
    template_name = 'blog/edit.html'
    model = BlogPost
    form_class = BlogPostForm
    context_object_name = 'post'

    def get_title(self):
        return _('Updating blog post')

    def get_content_title(self):
        return _('Updating blog post')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['edit'] = True
        context['delete'] = self.request.user.has_perm('judge.delete_blogpost')
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        with revisions.create_revision(atomic=True):
            revisions.set_comment(_('Edited from site'))
            revisions.set_user(self.request.user)
            return super(BlogPostEdit, self).form_valid(form)

    def dispatch(self, request, *args, **kwargs):
        if request.official_contest_mode and not request.user.is_superuser:
            return generic_message(request, _('Permission denied'),
                                   _('You cannot edit blog post.'))
        return super().dispatch(request, *args, **kwargs)


class BlogPostDelete(BlogPostMixin, SingleObjectMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.method != 'POST':
            return HttpResponseForbidden()

        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm('judge.delete_blogpost'):
            raise PermissionDenied()

        post = self.get_object()
        post.delete()
        return HttpResponseRedirect('/')
