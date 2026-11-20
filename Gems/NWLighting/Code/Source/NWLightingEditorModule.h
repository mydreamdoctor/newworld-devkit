/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#pragma once

#include <AzCore/Module/Module.h>

namespace NWLighting
{
    //! Editor module: registers only the editor wrapper. The runtime
    //! component is registered by NWLightingModule, which also loads in
    //! the editor; registering it here as well would duplicate the
    //! component and config UUIDs.
    class NWLightingEditorModule : public AZ::Module
    {
    public:
        AZ_RTTI(NWLightingEditorModule, "{7B2E3C8D-4E5F-4061-9B72-83C4D5E6F708}", AZ::Module);
        AZ_CLASS_ALLOCATOR(NWLightingEditorModule, AZ::SystemAllocator);

        NWLightingEditorModule();

        AZ::ComponentTypeList GetRequiredSystemComponents() const override;
    };
} // namespace NWLighting
