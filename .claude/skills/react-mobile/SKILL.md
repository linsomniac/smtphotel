---
name: react-mobile
description: Mobile-first React component development with Tailwind CSS, TanStack Query, and accessibility. Use when creating React components, pages, or hooks.
allowed-tools: Read, Edit, Bash, Grep, Glob
---

# Mobile-First React Development

This skill guides development of React components for the E-Signature Platform.

## Component Implementation Checklist

1. **Mobile-first CSS**: Use Tailwind's mobile-first breakpoints (sm:, md:, lg:)
2. **Touch targets**: Minimum 44px for all interactive elements
3. **Loading states**: Use Skeleton components, never spinners for content
4. **Empty states**: Always handle empty data with friendly messages
5. **Error boundaries**: Wrap complex components
6. **Accessibility**: aria-labels, proper semantics, keyboard navigation

## Touch Target Standards

```tsx
// GOOD: Large touch target (44px minimum)
<button className="min-h-[44px] min-w-[44px] p-3 flex items-center justify-center">
  <PlusIcon className="h-6 w-6" />
</button>

// BAD: Small touch target
<button className="p-1">
  <PlusIcon className="h-4 w-4" />
</button>

// GOOD: List item with adequate touch area
<li className="py-3 px-4 min-h-[48px] flex items-center">
  {content}
</li>
```

## Loading State Patterns

```tsx
// GOOD: Skeleton loading
function EnvelopeList() {
  const { data: envelopes, isLoading } = useEnvelopes();

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
    );
  }

  return <>{envelopes.map(env => <EnvelopeCard key={env.id} envelope={env} />)}</>;
}

// BAD: Spinner for content loading
function EnvelopeList() {
  if (isLoading) return <Spinner />;  // Don't do this
}
```

## Empty State Pattern

```tsx
function EnvelopeList() {
  const { data: envelopes } = useEnvelopes();

  if (envelopes.length === 0) {
    return (
      <EmptyState
        icon={<FileTextIcon />}
        title="No envelopes yet"
        description="Create your first envelope to get started"
        action={
          <Button onClick={openCreateEnvelope}>
            Create Envelope
          </Button>
        }
      />
    );
  }

  return <>{/* envelope list */}</>;
}
```

## TanStack Query Patterns

### Basic Query

```tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';

function useEnvelopes(status?: string) {
  return useQuery({
    queryKey: ['envelopes', status],
    queryFn: () => api.envelopes.list({ status }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
```

### Mutation with Optimistic Updates

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query';

function useCreateEnvelope() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.envelopes.create,

    // Optimistic update
    onMutate: async (newEnvelope) => {
      // Cancel outgoing queries
      await queryClient.cancelQueries({ queryKey: ['envelopes'] });

      // Snapshot previous value
      const previous = queryClient.getQueryData(['envelopes']);

      // Optimistically update
      queryClient.setQueryData(['envelopes'], (old: Envelope[]) => [
        { ...newEnvelope, id: 'temp-' + Date.now(), status: 'draft' },
        ...old,
      ]);

      return { previous };
    },

    // Rollback on error
    onError: (err, newEnvelope, context) => {
      queryClient.setQueryData(['envelopes'], context?.previous);
      toast.error('Failed to create envelope');
    },

    // Refetch on success
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['envelopes'] });
    },
  });
}
```

### Infinite Query (for lists)

```tsx
function useEnvelopesInfinite(status?: string) {
  return useInfiniteQuery({
    queryKey: ['envelopes', status],
    queryFn: ({ pageParam }) => api.envelopes.list({ status, cursor: pageParam }),
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    initialPageParam: undefined,
  });
}
```

## Component Structure

```tsx
// components/envelopes/EnvelopeCard.tsx
import { type Envelope } from '@/types';
import { formatDate } from '@/utils/formatters';

interface EnvelopeCardProps {
  envelope: Envelope;
  onEdit?: () => void;
}

export function EnvelopeCard({ envelope, onEdit }: EnvelopeCardProps) {
  return (
    <div
      className="bg-white rounded-lg shadow-sm p-4 min-h-[80px]"
      role="article"
      aria-label={`${envelope.name}, ${envelope.status}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">{envelope.name}</h3>
          <p className="text-sm text-gray-500">{formatDate(envelope.created_at)}</p>
        </div>
        <StatusBadge status={envelope.status} />
      </div>

      {onEdit && (
        <button
          onClick={onEdit}
          className="mt-2 min-h-[44px] w-full text-center text-blue-600"
          aria-label="Edit envelope"
        >
          Edit
        </button>
      )}
    </div>
  );
}
```

## Mobile Navigation Pattern

```tsx
// components/layout/BottomNav.tsx
const NAV_ITEMS = [
  { path: '/dashboard', icon: HomeIcon, label: 'Home' },
  { path: '/envelopes', icon: FileTextIcon, label: 'Envelopes' },
  { path: '/templates', icon: LayersIcon, label: 'Templates' },
  { path: '/settings', icon: SettingsIcon, label: 'Settings' },
];

export function BottomNav() {
  const location = useLocation();

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-white border-t safe-area-pb">
      <div className="flex justify-around">
        {NAV_ITEMS.map(({ path, icon: Icon, label }) => (
          <Link
            key={path}
            to={path}
            className={cn(
              "flex flex-col items-center py-2 px-4 min-w-[64px] min-h-[56px]",
              location.pathname === path ? "text-blue-600" : "text-gray-500"
            )}
            aria-current={location.pathname === path ? 'page' : undefined}
          >
            <Icon className="h-6 w-6" />
            <span className="text-xs mt-1">{label}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}
```

## Form Pattern (React Hook Form)

```tsx
import { useForm } from 'react-hook-form';

interface EnvelopeFormData {
  name: string;
  message?: string;
  expires_at?: string;
}

function CreateEnvelopeForm({ onSubmit }: { onSubmit: (data: EnvelopeFormData) => void }) {
  const { register, handleSubmit, formState: { errors } } = useForm<EnvelopeFormData>();

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label htmlFor="name" className="block text-sm font-medium">
          Envelope Name
        </label>
        <input
          id="name"
          {...register('name', { required: 'Name is required', maxLength: 255 })}
          className="mt-1 w-full rounded-md border p-3 min-h-[44px]"
          aria-invalid={errors.name ? 'true' : 'false'}
        />
        {errors.name && (
          <p className="mt-1 text-sm text-red-600" role="alert">
            {errors.name.message}
          </p>
        )}
      </div>

      <button
        type="submit"
        className="w-full bg-blue-600 text-white rounded-lg py-3 min-h-[44px] font-medium"
      >
        Create Envelope
      </button>
    </form>
  );
}
```

## After Implementation

```bash
# Lint check
npm run lint

# Type check
npm run type-check

# Run component tests
npm run test -- --watch
```

## File Organization

```
src/
├── components/
│   ├── ui/           # Base components (Button, Input, Modal)
│   ├── layout/       # App shell (BottomNav, Header)
│   ├── auth/         # Auth components
│   ├── envelopes/    # Envelope-specific components
│   ├── documents/    # Document viewer, upload
│   ├── fields/       # Field placement components
│   ├── signing/      # Signing flow components
│   └── templates/    # Template components
├── pages/            # Route components
├── hooks/            # Custom hooks (useEnvelopes, useAuth, useSigning)
├── api/              # API client and types
├── contexts/         # React contexts
└── utils/            # Formatters, validators
```
