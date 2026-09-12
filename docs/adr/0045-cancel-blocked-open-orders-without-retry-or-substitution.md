# Cancel blocked Open orders without retry or substitution

An order blocked at its intended Open is cancelled immediately: buys leave cash, sells leave the position, and no substitute instrument or deferred retry is created. A later Target Selection Update or changed Target Exposure starts from actual retained state and may create a new order; an unchanged exposure target does not keep a blocked order alive. A blocked reduction does not increase sales of other holdings to compensate, accepting visible target-versus-actual exposure differences rather than silently changing allocation.
