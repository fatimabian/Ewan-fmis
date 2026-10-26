from django.contrib.auth.mixins import LoginRequiredMixin


class FMISLoginRequiredMixin(LoginRequiredMixin):
    login_url = "authentication:login"
    default_page_size = 25
    allowed_page_sizes = (10, 25, 50, 100)

    def get_paginate_by(self, queryset):
        """Use bounded database pagination and reject abusive page sizes."""
        raw_page_size = self.request.GET.get("per_page", "")
        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError):
            page_size = self.default_page_size
        if page_size not in self.allowed_page_sizes:
            page_size = self.default_page_size
        return page_size

    def paginate_queryset(self, queryset, page_size):
        """Clamp malformed or stale page numbers instead of failing navigation."""
        paginator = self.get_paginator(
            queryset,
            page_size,
            orphans=self.get_paginate_orphans(),
            allow_empty_first_page=self.get_allow_empty(),
        )
        page_number = (
            self.kwargs.get(self.page_kwarg)
            or self.request.GET.get(self.page_kwarg)
            or 1
        )
        page = paginator.get_page(page_number)
        return paginator, page, page.object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page_obj = context.get("page_obj")
        if page_obj is None:
            return context

        preserved_fields = [
            (key, value)
            for key, values in self.request.GET.lists()
            if key != "page"
            for value in values
        ]
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(
            {
                "page_start_display": f"{page_obj.start_index():,}",
                "page_end_display": f"{page_obj.end_index():,}",
                "page_total_display": f"{page_obj.paginator.count:,}",
                "pages": page_obj.paginator.get_elided_page_range(
                    page_obj.number,
                    on_each_side=1,
                    on_ends=1,
                ),
                "ellipsis": page_obj.paginator.ELLIPSIS,
                "preserved_fields": preserved_fields,
                "preserved_query": query.urlencode(),
                "page_size": page_obj.paginator.per_page,
                "page_size_choices": self.allowed_page_sizes,
            }
        )
        return context
