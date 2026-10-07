from app.models import IssueStatus


def next_status(current_status: str, *, author_type: str, is_internal_note: bool = False) -> str:
    """Apply the fixed status state machine from PLAN.md to an incoming message.

    Two automatic transitions only:
      1. A Closed issue reopens (-> On You) when a new customer message arrives.
      2. Status -> On You when the customer replies last, On Customer when the team replies last.
    On Hold is a manual state and is never auto-changed by an incoming message.
    Internal notes aren't customer-facing replies, so they never trigger a transition.
    """
    if is_internal_note or current_status == IssueStatus.ON_HOLD.value:
        return current_status

    if author_type == "contact":
        return IssueStatus.ON_YOU.value

    if current_status == IssueStatus.CLOSED.value:
        return current_status

    return IssueStatus.ON_CUSTOMER.value


#On You	        Your team is working on it	            Counting
#On Customer	Waiting for the customer to reply	    Counting (per your spec)
#On Hold	    Nobody. Blocked by something external   (supplier, engineering fix, vendor)	Paused
#Closed	Done	Paused