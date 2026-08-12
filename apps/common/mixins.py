from django.contrib.auth.mixins import LoginRequiredMixin


class FMISLoginRequiredMixin(LoginRequiredMixin):
    login_url = "authentication:landing"

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
            }
        )
        return context
