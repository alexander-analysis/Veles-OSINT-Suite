import { useMemo, useState } from 'react';
import { Coins, RefreshCw, ExternalLink, Radio, Layers, Plus, CheckCircle2 } from 'lucide-react';
import clsx from 'clsx';
import PageHeader from '../components/common/PageHeader';
import StatusBadge from '../components/common/StatusBadge';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { useFetch } from '../hooks/useFetch';
import { apiPost } from '../services/api';

const CHAINS = ['bitcoin', 'ethereum', 'tron'];
const CHAIN_LABEL = { bitcoin: 'BTC', ethereum: 'ETH', tron: 'TRON', monero: 'XMR', litecoin: 'LTC', bitcoin_cash: 'BCH', zcash: 'ZEC', dash: 'DASH', solana: 'SOL', dogecoin: 'DOGE', bsc: 'BSC' };
const PATTERN_TONE = {
  exchange_cashout: 'error',
  exchange_withdrawal_to_sanctioned: 'error',
  sanctioned_mixer_usage: 'error',
  sanctioned_counterparty: 'error',
  mixer_usage: 'warn',
  whale_transfer: 'warn',
  watched_wallet_activity: 'neutral',
};
const TX_EXPLORER = {
  bitcoin: (h) => `https://mempool.space/tx/${h}`,
  ethereum: (h) => `https://etherscan.io/tx/${h.split(':')[0]}`,
  tron: (h) => `https://tronscan.org/#/transaction/${h}`,
};
const ADDR_EXPLORER = {
  bitcoin: (a) => `https://mempool.space/address/${a}`,
  ethereum: (a) => `https://etherscan.io/address/${a}`,
  tron: (a) => `https://tronscan.org/#/address/${a}`,
};

const usd = (v) => (v == null ? '-' : `$${Math.round(v).toLocaleString()}`);
const short = (a) => (a ? (a.length > 18 ? `${a.slice(0, 10)}…${a.slice(-6)}` : a) : '-');
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');
const label = (s) => (s || '').replace(/_/g, ' ');

function Addr({ chain, address, className }) {
  if (!address) return <span className="text-gray-400">-</span>;
  const href = ADDR_EXPLORER[chain]?.(address);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer noopener" className={clsx('font-mono hover:underline', className)} title={address}>{short(address)}</a>
  ) : <span className={clsx('font-mono', className)} title={address}>{short(address)}</span>;
}

function Summary({ summary, status }) {
  if (!summary) return null;
  const chains = summary.sanctioned_wallets || {};
  const patterns = summary.transactions_by_pattern || {};
  const flagged = Object.entries(patterns).filter(([p]) => p !== 'whale_transfer').reduce((s, [, n]) => s + n, 0);
  const stream = summary.btc_stream || {};
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5 mb-4">
      <div className="card py-3"><div className="card-title">Sanctioned wallets</div><div className="text-xl font-semibold mt-1">{summary.sanctioned_wallets_total}</div><div className="text-xs text-gray-500">{Object.entries(chains).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([c, n]) => `${CHAIN_LABEL[c] || c} ${n}`).join(' - ')}</div></div>
      <div className="card py-3"><div className="card-title">Balance in sanctioned wallets</div><div className="text-xl font-semibold mt-1">{usd(summary.sanctioned_balance_usd)}</div><div className="text-xs text-gray-500">{summary.sanctioned_wallets_active} active in the last {summary.hours} h</div></div>
      <div className="card py-3"><div className="card-title">Flagged transfers ({summary.hours}h)</div><div className="text-xl font-semibold mt-1">{flagged}</div><div className="text-xs text-gray-500">{usd(summary.sanctioned_volume_usd)} touching sanctioned parties</div></div>
      <div className="card py-3"><div className="card-title">Whale transfers ({summary.hours}h)</div><div className="text-xl font-semibold mt-1">{patterns.whale_transfer || 0}</div><div className="text-xs text-gray-500">BTC {usd(summary.prices?.BTC)} - ETH {usd(summary.prices?.ETH)}</div></div>
      <div className="card py-3"><div className="card-title flex items-center gap-1"><Radio size={12} aria-hidden="true" /> Live feeds</div><div className="mt-1 flex flex-wrap gap-1"><StatusBadge tone={stream.connected ? 'ok' : 'warn'}>BTC mempool {stream.connected ? 'live' : 'offline'}</StatusBadge><StatusBadge tone={status?.eth_last_block ? 'ok' : 'neutral'}>ETH block {status?.eth_last_block ? status.eth_last_block.toLocaleString() : 'pending'}</StatusBadge></div><div className="text-xs text-gray-500 mt-1">{stream.messages ? `${stream.messages.toLocaleString()} mempool tx seen` : 'stream starting'} - {summary.clusters} cluster(s)</div></div>
    </div>
  );
}

function WalletDetail({ chain, address, onClose }) {
  const { data, loading } = useFetch(chain && address ? `/api/blockchain/wallets/${chain}/${address}` : null, 0);
  if (!chain) return null;
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <span className="card-title">Wallet detail</span>
        <button type="button" onClick={onClose} className="text-xs text-gray-500 hover:underline">close</button>
      </div>
      {loading && !data && <LoadingSpinner label="Loading wallet" />}
      {data && (
        <div className="space-y-3 text-sm">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={data.wallet.is_sanctioned ? 'error' : data.wallet.wallet_type === 'mixer' ? 'warn' : 'neutral'}>{data.wallet.wallet_type}</StatusBadge>
              <span className="text-xs text-gray-500">{CHAIN_LABEL[chain] || chain}</span>
              {data.explorer_url && <a href={data.explorer_url} target="_blank" rel="noreferrer noopener" className="text-xs text-steel-700 inline-flex items-center gap-1 hover:underline"><ExternalLink size={11} aria-hidden="true" /> explorer</a>}
            </div>
            <div className="font-mono text-xs break-all mt-1">{data.wallet.address}</div>
            <div className="font-medium mt-1">{data.wallet.owner_name || data.wallet.label || 'unattributed'}</div>
            {data.wallet.label && data.wallet.owner_name && <div className="text-xs text-gray-500">{data.wallet.label}</div>}
          </div>
          <table className="kv-table">
            <tbody>
              <tr><td>Balance</td><td>{data.wallet.balance_native != null ? `${data.wallet.balance_native.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${CHAIN_LABEL[chain] === 'TRON' ? 'TRX' : CHAIN_LABEL[chain]}` : '-'} {data.wallet.balance_usd != null && <span className="text-gray-500">({usd(data.wallet.balance_usd)})</span>}</td></tr>
              {data.wallet.notes && <tr><td>Tokens</td><td>{data.wallet.notes}</td></tr>}
              <tr><td>Transactions</td><td>{data.wallet.transaction_count ?? '-'}</td></tr>
              <tr><td>Last active</td><td>{when(data.wallet.last_active)}</td></tr>
              <tr><td>Programmes</td><td>{(data.wallet.sanctions_programs || []).join(', ') || '-'}</td></tr>
              <tr><td>Risk</td><td>{data.wallet.risk_score != null ? Math.round(data.wallet.risk_score * 100) + '%' : '-'} {(data.wallet.risk_factors || []).join(', ')}</td></tr>
              <tr><td>Checked</td><td>{when(data.wallet.last_checked)}</td></tr>
            </tbody>
          </table>
          {data.cluster && (
            <div className="text-xs">
              <div className="card-title mb-1 flex items-center gap-1"><Layers size={12} aria-hidden="true" /> Co-spend cluster ({data.cluster.wallet_count} addresses)</div>
              <div className="font-mono break-all text-gray-600 max-h-24 overflow-y-auto">{(data.cluster.linked_addresses || []).slice(0, 40).join(' ')}</div>
            </div>
          )}
          <div>
            <div className="card-title mb-1">Recent transfers ({data.transactions.length})</div>
            {data.transactions.length ? (
              <ul className="space-y-1 text-xs max-h-72 overflow-y-auto">
                {data.transactions.map((t) => (
                  <li key={t.id} className="border border-gray-200 rounded px-2 py-1">
                    <div className="flex justify-between gap-2"><span className="font-medium">{usd(t.amount_usd)} {t.token_type}</span><span className="text-gray-500">{when(t.timestamp)}</span></div>
                    <div className="text-gray-600"><Addr chain={chain} address={t.from_address} /> → <Addr chain={chain} address={t.to_address} /> <StatusBadge tone={PATTERN_TONE[t.suspicious_pattern] || 'neutral'}>{label(t.suspicious_pattern)}</StatusBadge></div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-gray-500">No transfers recorded yet - the wallet is polled in rotation.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function AddWatch({ onAdded }) {
  const [form, setForm] = useState({ blockchain: 'ethereum', address: '', label: '', wallet_type: 'individual' });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      const w = await apiPost('/api/blockchain/wallets', { ...form, watch: true });
      setMessage(`Watching ${w.blockchain} ${short(w.address)}`);
      setForm({ ...form, address: '', label: '' });
      onAdded?.();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="card text-xs space-y-2">
      <div className="card-title flex items-center gap-1"><Plus size={12} aria-hidden="true" /> Watch an address</div>
      <div className="flex gap-1">
        <select value={form.blockchain} onChange={(e) => setForm({ ...form, blockchain: e.target.value })} className="border border-gray-300 rounded px-1 py-1 bg-white">{CHAINS.map((c) => <option key={c} value={c}>{CHAIN_LABEL[c]}</option>)}</select>
        <select value={form.wallet_type} onChange={(e) => setForm({ ...form, wallet_type: e.target.value })} className="border border-gray-300 rounded px-1 py-1 bg-white">{['individual', 'exchange', 'mixer', 'contract', 'unknown'].map((t) => <option key={t} value={t}>{t}</option>)}</select>
      </div>
      <input required value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} placeholder="address" className="w-full border border-gray-300 rounded px-2 py-1 font-mono" />
      <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="label (optional)" className="w-full border border-gray-300 rounded px-2 py-1" />
      <button type="submit" disabled={busy} className="px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-100 disabled:opacity-50">Add to watch list</button>
      {message && <div className="text-gray-600">{message}</div>}
    </form>
  );
}

export default function Blockchain() {
  const [chain, setChain] = useState('');
  const [walletType, setWalletType] = useState('sanctioned');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('balance');
  const [hours, setHours] = useState(24);
  const [txFilter, setTxFilter] = useState('flagged');
  const [selected, setSelected] = useState(null);
  const [starting, setStarting] = useState(false);

  const walletParams = useMemo(() => {
    const p = new URLSearchParams({ limit: '150', sort });
    if (chain) p.set('chain', chain);
    if (walletType) p.set('wallet_type', walletType);
    if (q.trim()) p.set('q', q.trim());
    return p.toString();
  }, [chain, walletType, q, sort]);
  const txParams = useMemo(() => {
    const p = new URLSearchParams({ hours: String(hours), limit: '100' });
    if (txFilter === 'flagged') p.set('involves_sanctioned', 'true');
    if (txFilter === 'mixer') p.set('involves_mixer', 'true');
    if (txFilter === 'whale') p.set('pattern', 'whale_transfer');
    if (chain) p.set('chain', chain);
    return p.toString();
  }, [hours, txFilter, chain]);

  const { data: summary, refetch: refetchSummary } = useFetch(`/api/blockchain/summary?hours=${hours}`, 60000);
  const { data: status } = useFetch('/api/blockchain/status', 30000);
  const { data: wallets, loading, refetch: refetchWallets } = useFetch(`/api/blockchain/wallets?${walletParams}`, 60000);
  const { data: txs, refetch: refetchTxs } = useFetch(`/api/blockchain/transactions?${txParams}`, 30000);

  const refreshAll = () => { refetchSummary(); refetchWallets(); refetchTxs(); };
  const collectNow = async () => {
    setStarting(true);
    try {
      await apiPost('/api/blockchain/refresh?job=all', {});
      setTimeout(refreshAll, 15000);
    } catch (err) {
      alert(err.message);
    } finally {
      setStarting(false);
    }
  };
  const ack = async (id) => {
    try {
      await apiPost(`/api/blockchain/transactions/${id}/acknowledge`, {});
      refetchTxs();
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div>
      <PageHeader title="Blockchain Tracker" subtitle="OFAC digital-currency addresses on Bitcoin, Ethereum and Tron - balances, movements, exchange cash-outs, mixer use and whale transfers">
        {status?.last_run?.poll && <span className="text-xs text-gray-500">Last poll {new Date(status.last_run.poll).toLocaleTimeString()}</span>}
        <button type="button" onClick={collectNow} disabled={starting} className="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 bg-white text-xs hover:bg-gray-100 disabled:opacity-50">
          <RefreshCw size={12} className={starting ? 'animate-spin' : ''} aria-hidden="true" /> Poll now
        </button>
      </PageHeader>

      <Summary summary={summary} status={status} />

      <div className="card mb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
          <label className="flex items-center gap-1">Chain
            <select value={chain} onChange={(e) => setChain(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="">all</option>{CHAINS.map((c) => <option key={c} value={c}>{CHAIN_LABEL[c]}</option>)}</select>
          </label>
          <label className="flex items-center gap-1">Wallets
            <select value={walletType} onChange={(e) => setWalletType(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white">
              <option value="sanctioned">sanctioned</option><option value="exchange">exchanges</option><option value="mixer">mixers</option><option value="individual">analyst-added</option><option value="delisted">delisted</option><option value="">all</option>
            </select>
          </label>
          <label className="flex items-center gap-1">Sort
            <select value={sort} onChange={(e) => setSort(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="balance">balance</option><option value="last_active">last active</option><option value="risk">risk</option><option value="owner">owner</option></select>
          </label>
          <label className="flex items-center gap-1">Search <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="owner, label, address" className="border border-gray-300 rounded px-1 py-0.5 w-44" /></label>
          <label className="flex items-center gap-1 ml-auto">Transfers
            <select value={txFilter} onChange={(e) => setTxFilter(e.target.value)} className="border border-gray-300 rounded px-1 py-0.5 bg-white"><option value="flagged">sanctioned parties</option><option value="mixer">mixer use</option><option value="whale">whales</option><option value="all">all recorded</option></select>
            <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="border border-gray-300 rounded px-1 py-0.5 bg-white">{[6, 24, 72, 168, 720].map((h) => <option key={h} value={h}>{h < 48 ? `${h} h` : `${h / 24} d`}</option>)}</select>
          </label>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <div className="card overflow-x-auto">
            <div className="flex items-center justify-between mb-2"><span className="card-title flex items-center gap-1"><Coins size={12} aria-hidden="true" /> Wallets ({wallets?.total ?? 0})</span>{loading && <span className="text-xs text-gray-400">loading</span>}</div>
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200">
                <tr><th className="py-1 pr-2 font-medium">Chain</th><th className="py-1 pr-2 font-medium">Address</th><th className="py-1 pr-2 font-medium">Owner / label</th><th className="py-1 pr-2 font-medium">Programmes</th><th className="py-1 pr-2 font-medium text-right">Balance</th><th className="py-1 pr-2 font-medium text-right">Txs</th><th className="py-1 font-medium">Last active</th></tr>
              </thead>
              <tbody>
                {(wallets?.wallets || []).map((w) => (
                  <tr key={w.id} onClick={() => setSelected({ chain: w.blockchain, address: w.address })} className={clsx('border-b border-gray-100 cursor-pointer hover:bg-gray-50', selected?.address === w.address && 'bg-steel-50')}>
                    <td className="py-1 pr-2 font-mono">{CHAIN_LABEL[w.blockchain] || w.blockchain}</td>
                    <td className="py-1 pr-2"><Addr chain={w.blockchain} address={w.address} /></td>
                    <td className="py-1 pr-2 max-w-[220px] truncate" title={w.label || ''}>{w.owner_name || w.label || '-'}{w.wallet_type === 'mixer' && <span className="ml-1 text-yellow-700">mixer</span>}</td>
                    <td className="py-1 pr-2 text-gray-500 max-w-[160px] truncate">{(w.sanctions_programs || []).join(', ')}</td>
                    <td className="py-1 pr-2 text-right font-mono">{usd(w.balance_usd)}</td>
                    <td className="py-1 pr-2 text-right font-mono">{w.transaction_count ?? '-'}</td>
                    <td className="py-1 text-gray-500 whitespace-nowrap">{w.last_active ? new Date(w.last_active).toLocaleDateString() : '-'}</td>
                  </tr>
                ))}
                {!wallets?.wallets?.length && !loading && <tr><td colSpan={7} className="py-2 text-gray-500">No wallets yet - the sync job runs a few minutes after the sanctions lists load.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card overflow-x-auto">
            <div className="card-title mb-2">Transfers ({txs?.total ?? 0})</div>
            <table className="w-full text-xs">
              <thead className="text-left text-gray-500 border-b border-gray-200">
                <tr><th className="py-1 pr-2 font-medium">Time</th><th className="py-1 pr-2 font-medium">Chain</th><th className="py-1 pr-2 font-medium text-right">Amount</th><th className="py-1 pr-2 font-medium">Pattern</th><th className="py-1 pr-2 font-medium">From → To</th><th className="py-1 font-medium">Tx</th></tr>
              </thead>
              <tbody>
                {(txs?.transactions || []).map((t) => (
                  <tr key={t.id} className={clsx('border-b border-gray-100', t.acknowledged && 'opacity-60')}>
                    <td className="py-1 pr-2 whitespace-nowrap text-gray-500">{when(t.timestamp)}</td>
                    <td className="py-1 pr-2 font-mono">{CHAIN_LABEL[t.blockchain] || t.blockchain}</td>
                    <td className="py-1 pr-2 text-right font-mono whitespace-nowrap">{usd(t.amount_usd)} <span className="text-gray-500">{t.token_type}</span></td>
                    <td className="py-1 pr-2"><StatusBadge tone={PATTERN_TONE[t.suspicious_pattern] || 'neutral'}>{label(t.suspicious_pattern)}</StatusBadge></td>
                    <td className="py-1 pr-2 max-w-[260px]">
                      <div className="truncate"><span className={t.source_entity ? 'font-medium' : 'text-gray-400'}>{t.source_entity || short(t.from_address)}</span> → <span className={t.destination_entity ? 'font-medium' : 'text-gray-400'}>{t.destination_entity || short(t.to_address)}</span></div>
                    </td>
                    <td className="py-1 whitespace-nowrap">
                      {TX_EXPLORER[t.blockchain] ? <a href={TX_EXPLORER[t.blockchain](t.tx_hash)} target="_blank" rel="noreferrer noopener" className="text-steel-700 hover:underline font-mono">{t.tx_hash.slice(0, 10)}…</a> : <span className="font-mono">{t.tx_hash.slice(0, 10)}…</span>}
                      {!t.acknowledged && t.involves_sanctioned && <button type="button" onClick={() => ack(t.id)} title="Acknowledge" className="ml-1 text-gray-400 hover:text-green-700 align-middle"><CheckCircle2 size={12} aria-hidden="true" /></button>}
                    </td>
                  </tr>
                ))}
                {!txs?.transactions?.length && <tr><td colSpan={6} className="py-2 text-gray-500">Nothing recorded in this window yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
        <div className="space-y-4">
          {selected ? <WalletDetail chain={selected.chain} address={selected.address} onClose={() => setSelected(null)} /> : (
            <div className="card text-sm text-gray-500">Select a wallet to see balances, tokens, co-spend clusters and its recent transfers. Bitcoin and Tron wallets are polled in rotation (about every 3-4 hours each); Ethereum balances are refreshed every poll and stablecoin flows are captured block by block.</div>
          )}
          <AddWatch onAdded={refetchWallets} />
          <div className="card text-xs text-gray-500">
            <div className="card-title mb-1">Collection status</div>
            <div>Sync: {status?.last_result?.sync ? `${status.last_result.sync.added} added, ${status.last_result.sync.updated} updated` : 'pending'}</div>
            <div>Poll: {status?.last_result?.poll ? `${status.last_result.poll.bitcoin} BTC, ${status.last_result.poll.ethereum} ETH, ${status.last_result.poll.tron} TRON wallets - ${status.last_result.poll.new_transactions} new transfers` : 'pending'}</div>
            <div>ETH scan: {status?.last_result?.scan ? `${status.last_result.scan.blocks} block(s) - ${status.last_result.scan.stored} stored` : 'pending'} - RPC calls {status?.rpc_calls ?? 0}</div>
            <div>BTC stream hits: {status?.stream_hits ?? 0}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
