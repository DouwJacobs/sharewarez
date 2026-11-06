"""One normalized, bounded query contract for admin delivery transports."""
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from sharewarez import db
from sharewarez.models import DownloadRequest, DownloadTransfer, User

FINISHED = ('completed', 'interrupted', 'cancelled')
LINK_STATES = ('available', 'pending', 'processing', 'failed', 'cancelled', 'expired', 'completed')


@dataclass(frozen=True)
class DeliveryFilters:
    view: str = 'activity'
    user: str = ''
    per_page: int = 25
    page: int = 1
    transfer_status: str = ''
    request_id: str = ''
    status: str = ''
    content_type: str = ''

    @classmethod
    def parse(cls, args):
        def text(key):
            value = args.get(key, '')
            if not isinstance(value, str):
                raise ValueError('Invalid filter')
            if hasattr(args, 'getlist') and len(args.getlist(key)) > 1:
                raise ValueError('Duplicate filter')
            return value.strip()

        view = text('view') or ('activity' if any(key in args for key in ('transfer_status', 'transfer_page'))
                               else 'links' if any(key in args for key in ('status', 'content_type', 'page')) else 'activity')
        if view not in ('activity', 'links'):
            raise ValueError('Invalid view')
        user = text('user')
        if len(user) > 255:
            raise ValueError('Invalid username filter')
        per_page = int(text('per_page') or '25')
        page = int(text('transfer_page' if view == 'activity' else 'page') or '1')
        if page < 1 or page > 1000000 or per_page < 10 or per_page > 100:
            raise ValueError('Invalid page')
        if view == 'activity':
            status = text('transfer_status').lower()
            request_id = text('request_id')
            if status and status not in ('active', *FINISHED):
                raise ValueError('Invalid transfer status')
            if request_id:
                number = int(request_id)
                if number < 1 or number > 2147483647:
                    raise ValueError('Invalid link ID')
                request_id = str(number)
            return cls(view, user, per_page, page, status, request_id)
        status, content = text('status').lower(), text('content_type').lower()
        if (status and status not in LINK_STATES) or (content and content not in ('game', 'update', 'extra')):
            raise ValueError('Invalid link filter')
        return cls(view, user, per_page, page, status=status, content_type=content)

    def params(self, *, page=None):
        result = dict(view=self.view, user=self.user, per_page=str(self.per_page))
        if self.view == 'activity':
            result.update(transfer_status=self.transfer_status, request_id=self.request_id,
                          transfer_page=str(self.page if page is None else page))
        else:
            result.update(status=self.status, content_type=self.content_type,
                          page=str(self.page if page is None else page))
        return result

    def url(self, *, page=None):
        return '/admin/manage-downloads?' + urlencode(self.params(page=page))

    def tab_url(self, view):
        return '/admin/manage-downloads?' + urlencode(dict(view=view, user=self.user, per_page=self.per_page))


def username_predicate(name):
    # Treat the search as a literal substring; '_' and '%' must not widen scope.
    escaped = name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return User.name.ilike(f'%{escaped}%', escape='\\')


def activity_predicates(filters, *, finished=False):
    result = [DownloadTransfer.admin_history_hidden_at.is_(None)]
    if filters.user:
        result.append(username_predicate(filters.user))
    if filters.transfer_status:
        result.append(DownloadTransfer.status == filters.transfer_status)
    if filters.request_id:
        result.append(DownloadTransfer.download_request_id == int(filters.request_id))
    if finished:
        result.append(DownloadTransfer.status.in_(FINISHED))
    return result


def finished_query(filters):
    return select(DownloadTransfer.id).join(User, DownloadTransfer.user_id == User.id).where(
        *activity_predicates(filters, finished=True))


def finished_count(filters):
    return db.session.scalar(select(func.count()).select_from(finished_query(filters).subquery()))


def delivery_page(filters):
    if filters.view == 'activity':
        query = select(DownloadTransfer).join(User, DownloadTransfer.user_id == User.id).where(
            *activity_predicates(filters)).options(
                joinedload(DownloadTransfer.user), joinedload(DownloadTransfer.game),
                joinedload(DownloadTransfer.download_request).joinedload(DownloadRequest.game),
            ).order_by(DownloadTransfer.started_at.desc(), DownloadTransfer.id.desc())
    else:
        query = select(DownloadRequest).join(User, DownloadRequest.user_id == User.id).options(
            joinedload(DownloadRequest.user), joinedload(DownloadRequest.game),
            joinedload(DownloadRequest.game_update), joinedload(DownloadRequest.game_extra),
        ).order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
        if filters.user:
            query = query.where(username_predicate(filters.user))
        if filters.status:
            query = query.where(DownloadRequest.status == filters.status)
        if filters.content_type:
            query = query.where(DownloadRequest.content_type == filters.content_type)
    return db.paginate(query, page=filters.page, per_page=filters.per_page, error_out=False)
