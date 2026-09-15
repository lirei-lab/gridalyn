# feeder_criticality_study

The study half of the `feeder_criticality` example extension (bd 4ky.8). It
declares the extension in `spec.inputs.extensions`, and its one building stage
asks the semantic build for the `feeder_criticality` capability, which gridalyn
does not ship. See `../run_example.py` for how to run it, with and without the
declaration.
