"""AI-based automatic block planning - Chennai Division pilot.

The planning system that consumes the data layer under ../data. Modules build up
in the pipeline order of Blueprint section 4:

    network   - the multigraph substrate (Blueprint 2)
    windows   - candidate window enumeration (Blueprint 5)
    ...clustering, optimiser, models, evaluation to follow.
"""
