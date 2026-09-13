"""Active / selected influence helpers."""


def active_local_index(obj, group_indices):
    vg = obj.vertex_groups.active
    if vg is None:
        return -1
    try:
        return list(group_indices).index(vg.index)
    except ValueError:
        return -1
