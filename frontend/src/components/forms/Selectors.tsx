"use client";

import type { Driver, Meeting, Season, Session } from "@/types/domain";

type SelectProps<T> = {
  label: string;
  value: string;
  items: T[];
  getValue: (item: T) => string;
  getLabel: (item: T) => string;
  onChange: (value: string) => void;
};

function Select<T>({ label, value, items, getValue, getLabel, onChange }: SelectProps<T>) {
  return (
    <label className="block text-sm text-slate-400">
      {label}
      <select
        className="control mt-1 h-10 w-full"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={!items.length}
      >
        {!items.length ? <option value="">No options available</option> : null}
        {items.map((item) => (
          <option key={getValue(item)} value={getValue(item)}>
            {getLabel(item)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SeasonSelector({
  seasons,
  value,
  onChange
}: {
  seasons: Season[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      label="Season"
      value={value}
      items={seasons}
      getValue={(season) => String(season.year)}
      getLabel={(season) => String(season.year)}
      onChange={onChange}
    />
  );
}

export function MeetingSelector({
  meetings,
  value,
  onChange
}: {
  meetings: Meeting[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      label="Meeting"
      value={value}
      items={meetings}
      getValue={(meeting) => meeting.meeting_id}
      getLabel={(meeting) => `R${meeting.round} ${meeting.name}`}
      onChange={onChange}
    />
  );
}

export function SessionSelector({
  sessions,
  value,
  onChange
}: {
  sessions: Session[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      label="Session"
      value={value}
      items={sessions}
      getValue={(session) => session.session_id}
      getLabel={(session) => `${session.type} ${session.name}`}
      onChange={onChange}
    />
  );
}

export function DriverSelector({
  drivers,
  value,
  onChange,
  label = "Driver"
}: {
  drivers: Driver[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <Select
      label={label}
      value={value}
      items={drivers}
      getValue={(driver) => driver.code}
      getLabel={(driver) => `${driver.code} - ${driver.full_name}`}
      onChange={onChange}
    />
  );
}

