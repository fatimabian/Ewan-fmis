from django import template


register = template.Library()


@register.filter
def fmis_intcomma(value):
    """Format table counts with readable thousands separators."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value


@register.inclusion_tag("shared/pagination.html", takes_context=True)
def fmis_pagination(context, page_obj):
    """Render accessible pagination while preserving current table filters."""
    request = context["request"]
    preserved_fields = [
        (key, value)
        for key, values in request.GET.lists()
        if key != "page"
        for value in values
    ]
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "page_obj": page_obj,
        "pages": page_obj.paginator.get_elided_page_range(
            page_obj.number,
            on_each_side=1,
            on_ends=1,
        ),
        "ellipsis": page_obj.paginator.ELLIPSIS,
        "preserved_fields": preserved_fields,
        "preserved_query": query.urlencode(),
    }
