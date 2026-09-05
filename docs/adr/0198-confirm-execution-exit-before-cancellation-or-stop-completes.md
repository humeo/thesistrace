# Confirm execution exit before cancellation or Stop completes

ResearchRun cancellation and DailyTrack Stop fence publication immediately, but their terminal states and Data Generation release require confirmation that active calculation has ended. Waiting for ownership recovery when a supervisor is lost sacrifices prompt completion reporting to prevent an abandoned child from publishing or reading collected data.
