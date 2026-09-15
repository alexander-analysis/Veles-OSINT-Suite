"""Curated on-chain labels: exchange deposit/hot wallets and mixers.

Public attributions widely reported by block explorers and the OFAC list.
Confidence is deliberately below 1.0 - exchanges rotate wallets, and the list
is a seed for analysts to extend through ``POST /api/blockchain/wallets``.
"""

# (blockchain, address, label, wallet_type, owner, confidence)
LABELS = [
    # --- Ethereum exchanges (well known hot wallets)
    ("ethereum", "0x28c6c06298d514db089934071355e5743bf21d60", "Binance 14", "exchange", "Binance", 0.8),
    ("ethereum", "0x21a31ee1afc51d94c2efccaa2092ad1028285549", "Binance 15", "exchange", "Binance", 0.8),
    ("ethereum", "0xdfd5293d8e347dfe59e90efd55b2956a1343963d", "Binance 16", "exchange", "Binance", 0.8),
    ("ethereum", "0x56eddb7aa87536c09ccc2793473599fd21a8b17f", "Binance 17", "exchange", "Binance", 0.8),
    ("ethereum", "0x9696f59e4d72e237be84ffd425dcad154bf96976", "Binance 18", "exchange", "Binance", 0.8),
    ("ethereum", "0x4976a4a02f38326660d17bf34b431dc6e2eb2327", "Binance 20", "exchange", "Binance", 0.8),
    ("ethereum", "0xf977814e90da44bfa03b6295a0616a897441acec", "Binance 8 (cold)", "exchange", "Binance", 0.8),
    ("ethereum", "0x71660c4005ba85c37ccec55d0c4493e66fe775d3", "Coinbase 1", "exchange", "Coinbase", 0.8),
    ("ethereum", "0x503828976d22510aad0201ac7ec88293211d23da", "Coinbase 2", "exchange", "Coinbase", 0.8),
    ("ethereum", "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740", "Coinbase 3", "exchange", "Coinbase", 0.8),
    ("ethereum", "0x3cd751e6b0078be393132286c442345e5dc49699", "Coinbase 4", "exchange", "Coinbase", 0.8),
    ("ethereum", "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43", "Coinbase 10", "exchange", "Coinbase", 0.8),
    ("ethereum", "0x2910543af39aba0cd09dbb2d50200b3e800a63d2", "Kraken 4", "exchange", "Kraken", 0.8),
    ("ethereum", "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13", "Kraken 5", "exchange", "Kraken", 0.8),
    ("ethereum", "0xe853c56864a2ebe4576a807d26fdc4a0ada51919", "Kraken 6", "exchange", "Kraken", 0.8),
    ("ethereum", "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b", "OKX", "exchange", "OKX", 0.8),
    ("ethereum", "0x98ec059dc3adfbdd63429454aeb0c990fba4a128", "OKX 2", "exchange", "OKX", 0.7),
    ("ethereum", "0x77134cbc06cb00b66f4c7e623d5fdbf6777635ec", "Bitfinex 2", "exchange", "Bitfinex", 0.8),
    ("ethereum", "0x1151314c646ce4e0efd76d1af4760ae66a9fe30f", "Bitfinex 3", "exchange", "Bitfinex", 0.8),
    ("ethereum", "0x0d0707963952f2fba59dd06f2b425ace40b492fe", "Gate.io", "exchange", "Gate.io", 0.7),
    ("ethereum", "0x2b5634c42055806a59e9107ed44d43c426e58258", "KuCoin", "exchange", "KuCoin", 0.7),
    ("ethereum", "0xf89d7b9c864f589bbf53a82105107622b35eaa40", "Bybit", "exchange", "Bybit", 0.7),
    ("ethereum", "0xee5b5b923ffce93a870b3104b7ca09c3db80047a", "Bybit 2", "exchange", "Bybit", 0.7),
    ("ethereum", "0x6262998ced04146fa42253a5c0af90ca02dfd2a3", "Crypto.com", "exchange", "Crypto.com", 0.7),
    ("ethereum", "0x46340b20830761efd32832a74d7169b29feb9758", "Crypto.com 2", "exchange", "Crypto.com", 0.7),
    ("ethereum", "0x5a52e96bacdabb82fd05763e25335261b270efcb", "Binance 28", "exchange", "Binance", 0.7),
    ("ethereum", "0xa7efae728d2936e78bda97dc267687568dd593f3", "OKX 3", "exchange", "OKX", 0.7),
    ("ethereum", "0x0548f59fee79f8832c299e01dca5c76f034f558e", "Garantex (sanctioned exchange)", "exchange", "Garantex", 0.8),
    # --- Ethereum mixers / privacy protocols (Tornado Cash pools and router)
    ("ethereum", "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc", "Tornado Cash 0.1 ETH", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936", "Tornado Cash 1 ETH", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf", "Tornado Cash 10 ETH", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xa160cdab225685da1d56aa342ad8841c3b53f291", "Tornado Cash 100 ETH", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xd4b88df4d29f5cedd6857912842cff3b20c8cfa3", "Tornado Cash 100 DAI", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xfd8610d20aa15b7b2e3be39b396a1bc3516c7144", "Tornado Cash 1000 DAI", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x07687e702b410fa43f4cb4af7fa097918ffd2730", "Tornado Cash 10000 DAI", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x23773e65ed146a459791799d01336db287f25334", "Tornado Cash 100000 DAI", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x169ad27a470d064dede56a2d3ff727986b15d52b", "Tornado Cash 100 USDT", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x0836222f2b2b24a3f36f98668ed8f0b38d1a872f", "Tornado Cash 1000 USDT", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xd96f2b1c14db8458374d9aca76e26c3d18364307", "Tornado Cash 100 USDC", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfba9d", "Tornado Cash 1000 USDC", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0x722122df12d4e14e13ac3b6895a86e84145b6967", "Tornado Cash Router", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xdd4c48c0b24039969fc16d1cdf626eab821d3384", "Tornado Cash Proxy", "mixer", "Tornado Cash", 0.95),
    ("ethereum", "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b", "Tornado Cash 10 ETH (legacy)", "mixer", "Tornado Cash", 0.9),
    ("ethereum", "0x8589427373d6d84e98730d7795d8f6f8731fda16", "Tornado Cash Gitcoin grants", "mixer", "Tornado Cash", 0.8),
    ("ethereum", "0xb541fc07bc7619fd4062a54d96268525cbc6ffef", "Railgun Relay", "mixer", "Railgun", 0.7),
    # --- Bitcoin exchanges (large, stable cold/hot wallets)
    ("bitcoin", "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "Binance cold wallet", "exchange", "Binance", 0.8),
    ("bitcoin", "3M219KR5vEneNb47ewrPfWyb5jQ2DjxRP6", "Binance", "exchange", "Binance", 0.7),
    ("bitcoin", "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h", "Binance hot wallet", "exchange", "Binance", 0.8),
    ("bitcoin", "1LQoWist8KkaUXSPKZHNvEyfrEkPHzSsCd", "Binance", "exchange", "Binance", 0.6),
    ("bitcoin", "3JZq4atUahhuA9rLhXLMhhTo133J9rF97j", "Bitfinex", "exchange", "Bitfinex", 0.7),
    ("bitcoin", "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97", "Bitfinex cold", "exchange", "Bitfinex", 0.7),
    ("bitcoin", "1Kr6QSydW9bFQG1mXiPNNu6WpJGmUa9i1g", "Bitfinex cold", "exchange", "Bitfinex", 0.7),
    ("bitcoin", "3Kzh9qAqVWQhEsfQz7zEQL1EuSx5tyNLNS", "Kraken", "exchange", "Kraken", 0.6),
    ("bitcoin", "bc1qa5wkgaew2dkv56kfvj49j0av5nml45x9ek9hz6", "Coinbase", "exchange", "Coinbase", 0.6),
    ("bitcoin", "3FHNBLobJnbCTFTVakh5TXmEneyf5PT61B", "Coinbase", "exchange", "Coinbase", 0.6),
    ("bitcoin", "bc1qjasf9z3h7w3jspkhtgatgpyvvzgpa2wwd2lr0eh5tx44reyn2k7sfc27a4", "Bitfinex", "exchange", "Bitfinex", 0.6),
    ("bitcoin", "12tkqA9xSoowkzoERHMWNKsTey55YEBqkv", "Garantex (sanctioned exchange)", "exchange", "Garantex", 0.7),
    ("bitcoin", "3FYSvvQJdzTKcHEAJN6QqQ1bxRk7BhVcy7", "Chatex (sanctioned exchange)", "exchange", "Chatex", 0.6),
    # --- Bitcoin mixers
    ("bitcoin", "bc1qw4cxpe6sxa5dg6sdwxjph959cw6yztrzl4r54s", "ChipMixer (seized)", "mixer", "ChipMixer", 0.6),
    ("bitcoin", "1AeoiHY23fbBn8QiJ5y6oAjrhRY1Fb85uc", "Blender.io (sanctioned mixer)", "mixer", "Blender.io", 0.7),
    ("bitcoin", "1BCwbHS6VrbeH2eT2pTuTn7A1ZW8KqTfjT", "Sinbad.io (sanctioned mixer)", "mixer", "Sinbad", 0.7),
    # --- Tron exchanges
    ("tron", "TAUN6FwrnwwmaEqYcckffC7wYmbaS6cBiX", "Binance hot (Tron)", "exchange", "Binance", 0.7),
    ("tron", "TV6MuMXfmLbBqPZvBHdwFsDnQeVfnmiuSi", "Binance (Tron)", "exchange", "Binance", 0.7),
    ("tron", "TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb", "Binance cold (Tron)", "exchange", "Binance", 0.7),
    ("tron", "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G", "OKX (Tron)", "exchange", "OKX", 0.6),
    ("tron", "TCzVehpgE3Jh6rTx47gvnhYT3YHGQ1hJ5o", "Bybit (Tron)", "exchange", "Bybit", 0.6),
    ("tron", "TQrY8tryqsYVCYS3MFbtffiPp2ccyn4STm", "Kraken (Tron)", "exchange", "Kraken", 0.6),
    ("tron", "TKCEtiMoAmWDSRepKDcahDYiA2ANrafDeg", "Garantex (Tron, sanctioned)", "exchange", "Garantex", 0.7),
]

STABLECOINS = {
    # contract -> (symbol, decimals)
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6),
    "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", 18),
}
TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
