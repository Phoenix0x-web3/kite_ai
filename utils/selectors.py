from dataclasses import dataclass


@dataclass
class Selector:
    name: str
    value: str


START = Selector(
    name="START",
    value="#root > div > main > div > div > div.layout-order__LayoutOrderedContent-sc-10pkjaa-0.layout__LayoutContent-sc-35hvts-1.bsryFm.fRkQSP > div.AnimateStyled-sc-__sc-nw4u3g-0.jPHXjX > div > section > div > div > div > div > div > div > div.InlineButtonWrapper-sc-__sc-1ndopc5-9.LlaGz > div:nth-child(1) > div > div > button > span > span > span",
)

YES = Selector(
    name="YES",
    value="#block-f228f718-f484-41aa-8099-cedb0f9c5ba6 > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div:nth-child(1) > div > div > ul > li:nth-child(1) > div > div",
)

TWITTER_INPUT = Selector(
    name="TWITTER",
    value="#block-17f22f4a-ed33-423e-a185-755b81352797 > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.InputWrapper-sc-__sc-26uh88-1.iApDbT > input",
)

OK_TWITTER = Selector(
    name="OK_TWITTER",
    value="#block-17f22f4a-ed33-423e-a185-755b81352797 > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.block-footer__Root-sc-1upe4h2-0.hlIUEI > div > div > div > div > div > button > span > span > span",
)


DISCORD_INPUT = Selector(
    name="DISCORD",
    value="#block-5fabec9e-12a8-47c6-8a5d-cd3e54046bff > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.InputWrapper-sc-__sc-26uh88-1.iApDbT > input",
)

OK_DISCORD = Selector(
    name="OK_DISCORD",
    value="#block-5fabec9e-12a8-47c6-8a5d-cd3e54046bff > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.block-footer__Root-sc-1upe4h2-0.hlIUEI > div > div > div > div > div > button > span > span > span",
)

ADDRESS_INPUT = Selector(
    name="ADDRESS",
    value="#block-8ba7905b-93de-476e-b084-2fb4a469445a > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.InputWrapper-sc-__sc-26uh88-1.iApDbT > input",
)

OK_ADDRESS = Selector(
    name="OK_ADDRESS",
    value="#block-8ba7905b-93de-476e-b084-2fb4a469445a > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.block-footer__Root-sc-1upe4h2-0.hlIUEI > div > div > div > div > div > button > span > span > span",
)

DESCRIPTION_INPUT = Selector(name="DESCRIPTION", value="textarea.auto-size-text-area")

SUMBIT_FORM = Selector(
    name="Submit",
    value="#block-c98afc51-7c80-408c-8e93-5d720a4a19cc > div > div > div.Root-sc-__sc-1ks3v0d-3.emMXAM > div > div > div > div > div.SpacerWrapper-sc-__sc-4rs8xl-0.frfGIQ > div > div.block-footer__Root-sc-1upe4h2-0.hlIUEI > div > div > div > div > div.Distribute-sc-__sc-5km20m-0.kgQkgV > div > div > button > span > span > span",
)
