# The live device tree names the USB hardware — and one pin matters

`stock_live.dtb` (1 123 092 B, 23 900 properties) was captured from the tablet
while it still booted. It is the richest hardware description in our possession,
and until now nobody had read the USB part of it. It answers some of what
`docs/39`–`docs/42` had to leave open.

---

    10|## 1. The PHY blocks, by address

```
/soc/hsphy@88e3000        high-speed PHY       <- the block FEDL and EUD read
/soc/ssphy@88e8000        superspeed PHY       <- matches ss_phy_cfg addresses
/soc/ssusb@a600000        the USB controller, with a dwc3 child
/soc/pinctrl@f000000/usb_phy_ps   port-select pins
```

This is the point that makes `docs/41` and `docs/42` concrete: the firmware reads
`0x088E2000` for EUD and `0x221C86xx` for FEDL, and `88e3000`/`88e8000` is exactly
where the device tree says the PHYs live. The static analysis and the hardware
description agree on the same silicon.

## 2. The port-select pin is `gpio29`

```
/soc/pinctrl@f000000/usb_phy_ps/usb3phy_portselect_default/mux
    pins     = "gpio29"
    function = "usb_phy"
/soc/pinctrl@f000000/usb_phy_ps/usb3phy_portselect_gpio/mux
    pins     = "gpio29"
    function = "gpio"
    config: bias-pull-down, input-enable, drive-strength 2
```

and the controller binds it:

```
/soc/ssusb@a600000   pinctrl-names = "default"
                     pinctrl-0     = <0x37c>      (the usb3phy_portselect_gpio node)
                     usb-role-switch              (present)
                     extcon       = <phandle>
                     gpios        = <phandle 0x1d 0>   -> gpio 29, active high
```

So there are **two functions on one pin**: the hardware port-select, and a plain
GPIO the software can drive. The `gpio` function with pull-down is the one the
boot path can use to force a state.

> **This is not yet a shorting instruction.** `gpio29` is an SoC TLMM pin, not a
> pad on the connector. Pulling it low is something the firmware does; it is not
> something a cable can do without opening the case. Recorded because it is the
> first named physical control for this port, and because it explains the
> `usb_phy_ps` behaviour the FEDL code depends on.

## 3. The pieces the firmware's `qusb_dci_dp_gnd_check` would use

```
/soc/qcom,spmi@c42d000/qcom,pm8550b@7/qcom,eusb2-repeater@fd00
    compatible = "qcom,pmic-eusb2-repeater"
    reg        = 0xfd00
    qcom,param-override-seq = 10 pairs of (register, value)
```

An **eUSB2 repeater on PM8550B** sits between the SoC PHY and the connector. That
matters for the FEDL question: a D+ condition can be detected by the repeater
rather than by the SoC PHY, which is consistent with the status word living at
`0x221C86xx` (an always-on block) rather than in the SS PHY at `0x088E8xxx`.

And:

```
/soc/qcom,spmi@c42d000/qcom,pmk8550@0/sdam@b600/usb-mode@50
    reg     = 0x50
```

`pmk8550` is the PMIC companion that owns the PMIC GLINK / SDAM transport. A
`usb-mode` register there is the natural place for "which USB mode is the port
in" to be published to software.

## 4. What this adds, and what it still does not

**Adds:**

- the PHY addresses the firmware reads are confirmed to be the real PHY blocks;
- there is a named software-controllable pin (`gpio29`) for port select;
- there is an eUSB2 repeater on PM8550B, i.e. the detection point for a D+
  condition need not be the SoC PHY;
- there is a `usb-mode` register in SDAM, which is a plausible source of the
  status word both FEDL and EUD consult.

**Still does not give:**

- a **connector pin-out**. The device tree describes the SoC side. Which pads on
  the Type-C receptacle to touch is a board-level fact and is not in any file we
  hold.
- proof that shorting anything sets the FEDL bit. That remains untested.

So route B in `docs/42` is still blocked, but the blocker is now precisely
described: **the SoC side is fully mapped, the connector side is not.**

## 5. Practical consequence

For a physical attempt there are now two distinguishable targets:

| target | how it would be reached | confidence |
|---|---|---|
| the Type-C receptacle's D+ pad | cable or probe, no disassembly | pin-out unknown |
| `gpio29` / the port-select net | needs the case open | named in DT, but it is a SoC pin |

The second is worse in effort and better in certainty. The first is the one worth
one more attempt, and it is the one `docs/43`'s vendor procedure also relies on -
which is another reason to try that procedure properly first: it needs the same
access, and it is free.
