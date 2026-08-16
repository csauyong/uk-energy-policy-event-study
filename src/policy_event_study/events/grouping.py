"""Event groups: mechanical dependence handled by grouping, not acknowledgement.

`docs/event_curation_protocol.md` Step 6. Two announcements closer together
than the spacing threshold share return days. That is **mechanical dependence,
not a soft correlation**: the same firms appear in both, on overlapping dates,
so the two are not two independent draws in any sense the inference can use.

The consequence for this project is specific and was not obvious. Clustering by
event and treating clusters as independent makes the wild bootstrap's p-value
floor a function of the *nominal* event count -- and that floor is the binding
constraint on what the design can claim (see `reports/dose_response.md` §2.1).
Two events nine days apart would inflate the apparent cluster count by one and
lower the reported floor, which is precisely backwards: dependence should
*raise* it.

So overlapping events are collapsed into one **group** by transitive closure
over the spacing threshold, and:

* the regression keeps **event** fixed effects -- each date's common market
  move still needs absorbing separately;
* standard errors cluster on the **group**;
* the bootstrap p-value floor is computed from the **number of groups**.

Transitive closure matters. Events on days 1, 10 and 19 with a 14-day threshold
form a single chain: 1-10 and 10-19 each overlap, so all three share return
days with a common neighbour and none of the three is independent of the
others. Pairwise grouping would leave 1 and 19 apart and overstate the cluster
count.

`overlap_ack` in the event dictionary therefore **declares a grouping rather
than waiving a check**. A fiscal event and its accompanying policy documents
are one event, not three.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import pandas as pd

from policy_event_study.events.schema import PolicyEvent

#: Default spacing threshold. Matches the event validator's.
DEFAULT_MIN_SPACING_DAYS: Final[int] = 14


@dataclass(frozen=True)
class EventGroup:
    """A set of events treated as one cluster for inference."""

    group_id: str
    event_ids: tuple[str, ...]
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def size(self) -> int:
        """Count the events collapsed into this group."""
        return len(self.event_ids)

    @property
    def is_collapsed(self) -> bool:
        """True where this group absorbed more than one event."""
        return self.size > 1

    @property
    def span_days(self) -> int:
        """Calendar days from the first to the last event in the group."""
        return int((self.end - self.start).days)


@dataclass(frozen=True)
class GroupingResult:
    """Outcome of grouping a curated event list."""

    groups: tuple[EventGroup, ...]
    assignment: Mapping[str, str]
    min_spacing_days: int

    @property
    def n_groups(self) -> int:
        """Count independent clusters -- this is what sets the p-value floor."""
        return len(self.groups)

    @property
    def n_events(self) -> int:
        """Count events nominally. Never report this without `n_groups`."""
        return len(self.assignment)

    @property
    def collapsed(self) -> tuple[EventGroup, ...]:
        """Groups that absorbed more than one event."""
        return tuple(group for group in self.groups if group.is_collapsed)

    def table(self) -> pd.DataFrame:
        """Render the grouping table for `make event-report` and the write-up."""
        return pd.DataFrame(
            [
                {
                    "group_id": group.group_id,
                    "n_events": group.size,
                    "span_days": group.span_days,
                    "start": group.start.date(),
                    "end": group.end.date(),
                    "event_ids": ", ".join(group.event_ids),
                }
                for group in self.groups
            ]
        )

    def summary(self) -> str:
        """One line for the curation view."""
        if self.n_events == self.n_groups:
            return (
                f"{self.n_events} event(s), {self.n_groups} group(s): all "
                f"{self.min_spacing_days}+ days apart, no collapsing."
            )
        return (
            f"{self.n_events} event(s) collapse to {self.n_groups} group(s) at a "
            f"{self.min_spacing_days}-day threshold. Inference clusters on "
            f"groups and the bootstrap floor is computed from "
            f"{self.n_groups}, not {self.n_events}."
        )


def assign_event_groups(
    events: Sequence[PolicyEvent],
    *,
    min_spacing_days: int = DEFAULT_MIN_SPACING_DAYS,
) -> GroupingResult:
    """Collapse events into groups by transitive closure over the spacing threshold.

    Parameters
    ----------
    events
        Curated events. Order does not matter; they are sorted internally.
    min_spacing_days
        Events whose announcements are closer than this share return days and
        join the same group.

    Returns
    -------
    GroupingResult
        Carrying both counts, because the nominal event count on its own
        overstates the independent information in the sample.
    """
    if not events:
        return GroupingResult(
            groups=(), assignment={}, min_spacing_days=min_spacing_days
        )

    ordered = sorted(events, key=lambda event: event.announcement_ts_utc)

    # Single pass is sufficient for the transitive closure: the events are
    # sorted, so a chain breaks exactly where consecutive gaps exceed the
    # threshold. Comparing against the previous event rather than the group's
    # start is what makes it transitive -- days 1, 10 and 19 chain into one
    # group even though 1 and 19 are 18 days apart.
    chains: list[list[PolicyEvent]] = [[ordered[0]]]
    for previous, current in itertools.pairwise(ordered):
        gap = (current.announcement_ts_utc - previous.announcement_ts_utc).days
        if gap < min_spacing_days:
            chains[-1].append(current)
        else:
            chains.append([current])

    groups: list[EventGroup] = []
    assignment: dict[str, str] = {}
    for chain in chains:
        group_id = chain[0].event_id if len(chain) == 1 else f"grp:{chain[0].event_id}"
        groups.append(
            EventGroup(
                group_id=group_id,
                event_ids=tuple(event.event_id for event in chain),
                start=chain[0].announcement_ts_utc,
                end=chain[-1].announcement_ts_utc,
            )
        )
        for event in chain:
            assignment[event.event_id] = group_id

    return GroupingResult(
        groups=tuple(groups),
        assignment=assignment,
        min_spacing_days=min_spacing_days,
    )


def attach_cluster_ids(
    frame: pd.DataFrame,
    grouping: GroupingResult,
    *,
    column: str = "cluster_id",
) -> pd.DataFrame:
    """Add a `cluster_id` column to a firm x event panel.

    The estimator clusters on this column when present. Event fixed effects
    still enter at the event level -- the grouping changes what counts as an
    independent cluster, not what counts as a common shock to absorb.

    Raises
    ------
    KeyError
        If any `event_id` in the frame has no group. Silently leaving a row
        unclustered would drop it from the sandwich estimator's meat matrix.
    """
    missing = sorted(set(frame["event_id"].astype(str)) - set(grouping.assignment))
    if missing:
        msg = (
            f"no group assigned for event(s) {missing}. Every event in the panel "
            "must be grouped before estimation, or its rows are silently excluded "
            "from the clustered variance"
        )
        raise KeyError(msg)
    return frame.assign(
        **{column: frame["event_id"].astype(str).map(grouping.assignment)}
    )
