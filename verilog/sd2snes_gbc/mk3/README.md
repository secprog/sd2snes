These are byte-for-byte copies of the MkIII GBC sources from
`274d52c8aa9c1970df2f04e39da1b5ddca8e6e25`, before the MkII port.
The corresponding parent files select the MkII port with `MK2`, and include
these originals otherwise. MkIII keeps its original MSU-1 interface, DAC,
register protocol, rendering and memory implementation.

`check-gbc-board-isolation.py` runs in GitHub Actions. It compares preprocessed
MkIII source tokens and project/IP files against that commit, and MkII tokens
against the accepted layout source `0cd924f1`. This prevents board-specific
work from silently changing the other implementation.
