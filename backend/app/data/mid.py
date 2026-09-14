"""ITU Maritime Identification Digits -> ISO 3166-1 alpha-2 (public ITU allocation table)."""

MID_TO_ISO: dict[str, str] = {}


def _add(iso: str, *mids: int) -> None:
    for mid in mids:
        MID_TO_ISO[str(mid)] = iso


# Europe
_add("AL", 201); _add("AD", 202); _add("AT", 203); _add("PT", 204, 255, 263); _add("BE", 205); _add("BY", 206)
_add("BG", 207); _add("VA", 208); _add("CY", 209, 210, 212); _add("DE", 211, 218); _add("GE", 213); _add("MD", 214)
_add("MT", 215, 229, 248, 249, 256); _add("AM", 216); _add("DK", 219, 220); _add("ES", 224, 225); _add("FR", 226, 227, 228)
_add("FI", 230); _add("FO", 231); _add("GB", 232, 233, 234, 235); _add("GI", 236); _add("GR", 237, 239, 240, 241)
_add("HR", 238); _add("MA", 242); _add("HU", 243); _add("NL", 244, 245, 246); _add("IT", 247); _add("IE", 250)
_add("IS", 251); _add("LI", 252); _add("LU", 253); _add("MC", 254); _add("PL", 261); _add("ME", 262)
_add("RO", 264); _add("SE", 265, 266); _add("SK", 267); _add("SM", 268); _add("CH", 269); _add("CZ", 270)
_add("TR", 271); _add("UA", 272); _add("RU", 273); _add("MK", 274); _add("LV", 275); _add("EE", 276); _add("LT", 277)
_add("SI", 278); _add("RS", 279)
# North & Central America, Caribbean
_add("AI", 301); _add("US", 303, 338, 366, 367, 368, 369); _add("AG", 304, 305); _add("CW", 306); _add("AW", 307)
_add("BS", 308, 309, 311); _add("BM", 310); _add("BZ", 312); _add("BB", 314); _add("CA", 316); _add("KY", 319)
_add("CR", 321); _add("CU", 323); _add("DM", 325); _add("DO", 327); _add("GP", 329); _add("GD", 330); _add("GL", 331)
_add("GT", 332); _add("HN", 334); _add("HT", 336); _add("JM", 339); _add("MQ", 347); _add("MS", 348); _add("MX", 345)
_add("NI", 350); _add("PA", 351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374); _add("PR", 358)
_add("SV", 359); _add("KN", 341); _add("LC", 343); _add("PM", 361); _add("VC", 375, 376, 377); _add("TT", 362)
_add("TC", 364); _add("VG", 378); _add("VI", 379)
# Asia
_add("AF", 401); _add("SA", 403); _add("BD", 405); _add("BH", 408); _add("BT", 410); _add("CN", 412, 413, 414)
_add("TW", 416); _add("LK", 417); _add("IN", 419); _add("IR", 422); _add("AZ", 423); _add("IQ", 425); _add("IL", 428)
_add("JP", 431, 432); _add("TM", 434); _add("KZ", 436); _add("UZ", 437); _add("JO", 438); _add("KR", 440, 441)
_add("PS", 443); _add("KP", 445); _add("KW", 447); _add("LB", 450); _add("KG", 451); _add("MO", 453); _add("MV", 455)
_add("MN", 457); _add("NP", 459); _add("OM", 461); _add("PK", 463); _add("QA", 466); _add("SY", 468); _add("AE", 470, 471)
_add("TJ", 472); _add("YE", 473, 475); _add("HK", 477); _add("BA", 478)
# Oceania
_add("AU", 503); _add("MM", 506); _add("BN", 508); _add("FM", 510); _add("PW", 511); _add("NZ", 512); _add("KH", 514, 515)
_add("CX", 516); _add("CK", 518); _add("FJ", 520); _add("CC", 523); _add("ID", 525); _add("KI", 529); _add("LA", 531)
_add("MY", 533); _add("MP", 536); _add("MH", 538); _add("NR", 542); _add("NC", 540); _add("NU", 544); _add("PG", 553)
_add("PH", 548); _add("PF", 546); _add("PN", 555); _add("SB", 557); _add("AS", 559); _add("WS", 561); _add("SG", 563, 564, 565, 566)
_add("TH", 567); _add("TO", 570); _add("TV", 572); _add("VN", 574); _add("VU", 576, 577); _add("WF", 578)
# Africa
_add("ZA", 601); _add("AO", 603); _add("DZ", 605); _add("SH", 607); _add("IO", 608); _add("BI", 609); _add("BJ", 610)
_add("BW", 611); _add("CF", 612); _add("CM", 613); _add("CG", 615); _add("KM", 616); _add("CV", 617); _add("TF", 618)
_add("CI", 619); _add("DJ", 621); _add("EG", 622); _add("ET", 624); _add("ER", 625); _add("GA", 626); _add("GH", 627)
_add("GM", 629); _add("GW", 630); _add("GQ", 631); _add("GN", 632); _add("BF", 633); _add("KE", 634); _add("LR", 636, 637)
_add("LY", 642); _add("LS", 644); _add("MU", 645); _add("MG", 647); _add("ML", 649); _add("MZ", 650); _add("MR", 654)
_add("MW", 655); _add("NE", 656); _add("NG", 657); _add("NA", 659); _add("RE", 660); _add("RW", 661); _add("SD", 662)
_add("SN", 663); _add("SC", 664); _add("SL", 667); _add("SO", 666); _add("ST", 668); _add("SZ", 669); _add("TD", 670)
_add("TG", 671); _add("TN", 672); _add("TZ", 674, 677); _add("UG", 675); _add("CD", 676); _add("ZM", 678); _add("ZW", 679)
# South America
_add("AR", 701); _add("BR", 710); _add("BO", 720); _add("CL", 725); _add("CO", 730); _add("EC", 735); _add("FK", 740)
_add("GF", 745); _add("GY", 750); _add("PY", 755); _add("PE", 760); _add("SR", 765); _add("UY", 770); _add("VE", 775)
