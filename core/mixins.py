"""
Access control at the view layer.

Hiding a button in a template is decoration — anyone can still type the URL.
Every screen that writes data must carry one of the mixins below.
"""

from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.shortcuts import redirect


class RoleRequiredMixin(LoginRequiredMixin, AccessMixin):
    """Base class: require sign-in, then check the role."""

    permission_denied_message = "You do not have permission to do that."

    def has_role_permission(self) -> bool:
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.has_role_permission():
            messages.error(request, self.permission_denied_message)
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class CanRecordMixin(RoleRequiredMixin):
    """Technician and above: log work, report incidents, move stock."""

    def has_role_permission(self) -> bool:
        return self.request.user.can_record


class CanManageMixin(RoleRequiredMixin):
    """Manager and above: create equipment, plan schedules, edit catalogs."""

    permission_denied_message = "Only a Manager or Administrator can do that."

    def has_role_permission(self) -> bool:
        return self.request.user.can_manage


class AdminRequiredMixin(RoleRequiredMixin):
    """Administrators only: delete records, manage users."""

    permission_denied_message = "Only an Administrator can do that."

    def has_role_permission(self) -> bool:
        return self.request.user.is_admin
